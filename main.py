import fitz
import json
import os
import re
from pathlib import Path
from collections import Counter
import unicodedata
import logging

# Set up logging for better error handling
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
    logging.StreamHandler()
    ]

)
logger = logging.getLogger(__name__)

def clean_text(text):
    """Cleans text by normalizing whitespace, fixing OCR artifacts, and handling multilingual characters."""
    if not text:
        return ""
    # Normalize Unicode characters (e.g., for Japanese, Chinese, etc.)
    text = unicodedata.normalize('NFKC', text)
    # Replace common OCR artifacts
    text = text.replace("ﬁ", "fi").replace("ﬂ", "fl").strip()
    # Normalize whitespace
    text = re.sub(r'\s+', ' ', text)
    return text

class BaseStrategy:
    """Base class for different document extraction strategies."""
    def __init__(self, doc):
        self.doc = doc

    def extract(self):
        raise NotImplementedError

    def _structure_headings(self, headings):
        """Assigns H1/H2/H3 levels based on style hierarchy and numbering."""
        if not headings: return []
        
        headings.sort(key=lambda h: (h['page'], h['bbox'][1]))
        
        heading_styles = sorted(list({h['style'] for h in headings}), key=lambda x: (x[0], x[1]), reverse=True)

        outline = []
        for h in headings:
            match = re.match(r'^(\d+(\.\d+)*)', h['text'])
            if match:
                level = min(match.group(1).count('.') + 1, 3)
            else:
                try:
                    rank = heading_styles.index(h['style'])
                    level = min(rank + 1, 3)
                except ValueError: level = 3
            outline.append({"level": f"H{level}", "text": h['text'], "page": h['page'] + 1})

        unique_outline = []
        seen = set()
        for item in outline:
            identifier = (item['text'], item['page'])
            if identifier not in seen:
                unique_outline.append(item)
                seen.add(identifier)

        return self._post_process_outline(unique_outline)

    def _post_process_outline(self, outline):
        """Corrects heading hierarchy."""
        if not outline: return []
        final_outline = [outline[0]]
        for i in range(1, len(outline)):
            current_item = outline[i]
            last_level_num = int(final_outline[-1]['level'][1])
            current_level_num = int(current_item['level'][1])
            if current_level_num > last_level_num + 1:
                current_item['level'] = f"H{last_level_num + 1}"
            final_outline.append(current_item)
        return final_outline


class TOCStrategy(BaseStrategy):
    """Strategy for documents with a reliable Table of Contents."""
    def extract(self):
        title = self._extract_title()
        toc = self.doc.get_toc()
        outline = self._process_toc(toc)
        return {"title": title, "outline": outline}

    def _extract_title(self):
        """Extracts title using font size, centering, and keyword-based fallbacks."""
        if self.doc.page_count == 0:
            return ""
        page = self.doc[0]
        page_width = page.rect.width
        blocks = [b for b in page.get_text("dict")["blocks"] if b['type'] == 0 and b['bbox'][3] < page.rect.height * 0.6]
        if not blocks:
            return ""

        # Primary: Look for largest font size in top half
        spans = [s for b in blocks for l in b['lines'] for s in l['spans'] if s['text'].strip()]
        if spans:
            top_size = max(s['size'] for s in spans)
            title_candidates = [s for s in spans if round(s['size']) >= round(top_size * 0.9)]
            if title_candidates:
                title_text = " ".join(s['text'] for s in title_candidates if round(s['size']) == round(top_size))
                return clean_text(title_text)

        # Fallback 1: Look for centered text
        for block in blocks:
            bbox = block['bbox']
            center_pos = (bbox[0] + bbox[2]) / 2
            if abs(center_pos - page_width / 2) < page_width * 0.25:
                text = clean_text(" ".join(s['text'] for l in block['lines'] for s in l['spans']))
                if text and len(text.split()) < 20:
                    return text

        # Fallback 2: Look for keywords like "Title" or "Abstract"
        for block in blocks:
            text = clean_text(" ".join(s['text'] for l in block['lines'] for s in l['spans']))
            if re.search(r'\b(title|abstract)\b', text, re.IGNORECASE):
                return text

        return ""

    def _process_toc(self, toc):
        outline = []
        for level, title, page in toc:
            if level <= 3:
                cleaned_title = clean_text(re.sub(r'\s+\.{2,}\s*\d+', '', title))
                if len(cleaned_title) > 2 and not cleaned_title.isdigit():
                    sub_headings = re.split(r'(?=\d+(\.\d+)+\s)', cleaned_title)
                    for sub_heading in sub_headings:
                        if sub_heading.strip():
                            outline.append({"level": f"H{level}", "text": sub_heading.strip(), "page": page + 1})
        return self._post_process_outline(outline)


class HeuristicStrategy(BaseStrategy):
    """Generic strategy for standard, text-heavy documents based on scoring text properties."""
    def __init__(self, doc):
        super().__init__(doc)
        self.font_stats = self._analyze_font_stats()
        self.body_size = self._get_dominant_font_size()

    def _analyze_font_stats(self):
        counts = Counter()
        for page in self.doc:
            for block in page.get_text("dict", flags=0)["blocks"]:
                if block['type'] == 0:
                    for line in block["lines"]:
                        for span in line["spans"]:
                            if span['text'].strip():
                                counts[round(span['size'])] += len(span['text'].strip())
        return counts

    def _get_dominant_font_size(self):
        if not self.font_stats: return 10
        return self.font_stats.most_common(1)[0][0]

    def extract(self):
        title = self._extract_title()
        headings = self._find_headings()
        outline = self._structure_headings(headings)
        return {"title": title, "outline": outline}

    def _extract_title(self):
        """Extracts title using font size, centering, and keyword-based fallbacks."""
        if self.doc.page_count == 0:
            return ""
        page = self.doc[0]
        page_width = page.rect.width
        blocks = [b for b in page.get_text("dict")["blocks"] if b['type'] == 0 and b['bbox'][3] < page.rect.height * 0.6]
        if not blocks:
            return ""

        # Primary: Look for largest font size in top half
        spans = [s for b in blocks for l in b['lines'] for s in l['spans'] if s['text'].strip()]
        if spans:
            top_size = max(s['size'] for s in spans)
            title_candidates = [s for s in spans if round(s['size']) >= round(top_size * 0.9)]
            if title_candidates:
                title_text = " ".join(s['text'] for s in title_candidates if round(s['size']) == round(top_size))
                return clean_text(title_text)

        # Fallback 1: Look for centered text
        for block in blocks:
            bbox = block['bbox']
            center_pos = (bbox[0] + bbox[2]) / 2
            if abs(center_pos - page_width / 2) < page_width * 0.25:
                text = clean_text(" ".join(s['text'] for l in block['lines'] for s in l['spans']))
                if text and len(text.split()) < 20:
                    return text

        # Fallback 2: Look for keywords like "Title" or "Abstract"
        for block in blocks:
            text = clean_text(" ".join(s['text'] for l in block['lines'] for s in l['spans']))
            if re.search(r'\b(title|abstract)\b', text, re.IGNORECASE):
                return text

        return ""

    def _find_headings(self):
        headings = []
        for page_num, page in enumerate(self.doc):
            blocks = page.get_text("dict")["blocks"]
            for b in blocks:
                if b['type'] != 0 or not b['lines']: continue
                block_text = clean_text(" ".join(s['text'] for l in b['lines'] for s in l['spans']))
                if not block_text: continue
                if b['bbox'][1] < 50 or b['bbox'][3] > page.rect.height - 50: continue

                score = 0
                first_span = b['lines'][0]['spans'][0]
                size = round(first_span['size'])
                is_bold = "bold" in first_span['font'].lower()

                if size > self.body_size: score += (size - self.body_size) * 5
                if is_bold: score += 10
                if len(block_text.split()) < 12: score += 10
                if not block_text.endswith(('.', ':', ';')): score += 5
                if re.match(r'^((\d+(\.\d+)*)|(Appendix\s+[A-Z])|([IVXLCDM]+\.))\b', block_text): score += 30
                if len(block_text.split()) > 25 or ('.' in block_text[1:-1] and len(block_text) > 30): score -= 20

                if score >= 25:
                    headings.append({'text': block_text, 'page': page_num, 'style': (size, is_bold), 'bbox': b['bbox']})
        return headings


class FormStrategy(HeuristicStrategy):
    """Strategy for forms, which typically have a title but no hierarchical outline."""
    def extract(self):
        title = self._extract_title()
        return {"title": title, "outline": []}


class VisualLayoutStrategy(HeuristicStrategy):
    """
    A generic strategy for visually-driven documents (e.g., flyers, invitations).
    It scores text blocks based on layout cues like spacing, centering, and typography
    to identify headings without relying on specific content.
    """
    def extract(self):
        headings = []
        for page_num, page in enumerate(self.doc):
            page_width = page.rect.width
            blocks = sorted(page.get_text("dict")["blocks"], key=lambda b: b['bbox'][1])
            
            for i, b in enumerate(blocks):
                if b['type'] != 0 or not b['lines']: continue

                block_text = clean_text(" ".join(s['text'] for l in b['lines'] for s in l['spans']))
                if not block_text or len(block_text) < 4: continue

                score = 0
                bbox = b['bbox']
                
                # Cue 1: Vertical whitespace (Isolation). A large gap above is a strong signal.
                space_above = bbox[1] - blocks[i-1]['bbox'][3] if i > 0 else 100
                if space_above > 10: score += 25
                
                # Cue 2: Centering.
                center_pos = (bbox[0] + bbox[2]) / 2
                if abs(center_pos - page_width / 2) < page_width * 0.25: score += 20

                # Cue 3: Font size (Prominence).
                first_span = b['lines'][0]['spans'][0]
                size = round(first_span['size'])
                if size > self.body_size + 1: score += (size - self.body_size) * 5
                
                # Cue 4: Brevity and Case.
                if len(block_text.split()) < 6: score += 10
                if block_text.isupper() and len(block_text.split()) > 1: score += 15
                
                # --- Contextual Penalties (Flexible) ---
                # Penalize if it's part of a dense list.
                space_below = blocks[i+1]['bbox'][1] - bbox[3] if i < len(blocks) - 1 else 100
                if space_below < 8: score -= 25
                
                # Penalize paragraph-like text.
                if len(block_text.split()) > 10 or '.' in block_text[:-1]: score -= 25
                
                # Penalize labels or noisy text based on generic patterns.
                noise_pattern = r':|\/|www\.|\.com|address|required|waiver|parents|regular pathway'
                if re.search(noise_pattern, block_text, re.IGNORECASE):
                    score -= 20 # Moderate penalty that can be overcome
                
                # Generic boost for short, exclamatory phrases (common in calls to action).
                if "!" in block_text and len(block_text.split()) < 6:
                    score += 30

                if score >= 40: # Higher threshold to ensure only strong candidates pass
                     is_bold = "bold" in first_span['font'].lower()
                     # If a call-to-action phrase is found, extract it cleanly.
                     match = re.search(r'([A-Z\s]+!)', block_text)
                     if match:
                         headings.append({'text': match.group(1).strip(), 'page': page_num, 'style': (size, is_bold), 'bbox': b['bbox']})
                     else:
                         headings.append({'text': block_text, 'page': page_num, 'style': (size, is_bold), 'bbox': b['bbox']})

        outline = self._structure_headings(headings)
        return {"title": "", "outline": outline}


class PDFOutlineExtractor:
    """Dispatcher class that selects the appropriate strategy based on document characteristics."""
    def __init__(self, doc):
        self.doc = doc
        self.strategy = self._get_strategy()

    def _get_strategy(self):
        if self.doc.page_count == 0: return HeuristicStrategy(self.doc)
        
        toc = self.doc.get_toc()
        if toc and len(toc) > 5:
            return TOCStrategy(self.doc)

        first_page_text = self.doc[0].get_text("text", flags=0).lower()
        
        if "application form" in first_page_text or "grant of" in first_page_text:
            return FormStrategy(self.doc)

        if self.doc.page_count <= 2:
            total_words = sum(len(p.get_text("words")) for p in self.doc)
            if total_words < 800:
                return VisualLayoutStrategy(self.doc)
        
        return HeuristicStrategy(self.doc)

    def extract(self):
        return self.strategy.extract()

def main():
    """Main execution function to process all PDFs in the input directory."""
    input_dir = Path(os.environ.get("INPUT_DIR", "/app/input"))
    output_dir = Path(os.environ.get("OUTPUT_DIR", "/app/output"))
    output_dir.mkdir(parents=True, exist_ok=True)

    for pdf_path in input_dir.glob("*.pdf"):
        logger.info(f"Processing {pdf_path.name}...")
        output_path = output_dir / f"{pdf_path.stem}.json"
        result = {"title": "", "outline": []}

        try:
            doc = fitz.open(pdf_path)
            extractor = PDFOutlineExtractor(doc)
            result = extractor.extract()
            doc.close()
            
            # Ensure no trailing spaces in output
            title = result.get('title', "")
            if title:
                result['title'] = title.strip()
            
            for item in result.get('outline', []):
                item['text'] = item['text'].strip()
            
            logger.info(f"Successfully processed {pdf_path.name}")
        except fitz.FileDataError as e:
            logger.error(f"Corrupted PDF file {pdf_path.name}: {str(e)}")
        except MemoryError as e:
            logger.error(f"Memory error processing {pdf_path.name}: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error processing {pdf_path.name}: {str(e)}")
        
        try:
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=4)
        except Exception as e:
            logger.error(f"Failed to write output for {pdf_path.name}: {str(e)}")

if __name__ == "__main__":
    main()