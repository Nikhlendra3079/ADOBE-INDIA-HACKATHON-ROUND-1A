# Round 1A: Understand Your Document

## Challenge Theme: Connecting the Dots Through Docs

## Approach

This solution extracts a structured outline from PDF documents using a dynamic, multi-strategy approach that avoids hardcoded, file-specific logic. It intelligently analyzes each document's intrinsic properties to determine the best extraction method, adhering to the principle of building a truly general-purpose tool.

The core of the solution is a pipeline that classifies and processes documents as follows:

1.  **Document Type Classification**: The script first performs a quick analysis to classify the document into one of three categories without using filenames:
    * **Forms**: Documents containing keywords like "Application Form" or "Signature" and exhibiting a form-like structure are identified. The extractor correctly concludes these have no hierarchical outline.
    * **Posters/Flyers**: Single-page documents with large, decorative fonts and minimal text are classified as flyers. For these, the most prominent text is extracted as a single H1 heading, and the title is left empty, reflecting their typical structure.
    * **Standard Reports**: Any document not classified as a form or flyer is treated as a standard report or article.

2.  **Primary Extraction Strategy (Table of Contents)**: For documents identified as standard reports, the most reliable source of structure is the embedded Table of Contents (TOC).
    * The script uses `PyMuPDF`'s `get_toc()` method to retrieve the author-defined outline.
    * If a valid TOC with a sufficient number of entries is found, it is used as the definitive source for the outline.
    * This method includes logic to detect the page on which the TOC itself resides, allowing it to accurately adjust the page numbers of all subsequent headings to ensure they align with the document's content pages.

3.  **Fallback Extraction Strategy (Heuristic Analysis)**: If a document does not have a usable TOC, the script seamlessly falls back to a manual, heuristic-based engine. This engine analyzes multiple features of the text:
    * **Typographical Analysis**: It first profiles the entire document to find the statistical mode of font sizes, which is designated as the "body text" size. All larger font sizes are marked as potential heading styles and ranked to form a hierarchy (H1, H2, H3).
    * **Content-Based Rules**: It gives the highest priority to content-based signals. Text prefixed with numerical patterns (e.g., `1.`, `2.1`, `3.1.2`) is immediately and confidently classified as a heading of the corresponding level.
    * **Layout and Style Analysis**: For non-numbered text, the classification is based on a combination of font size, font weight (bold), and position on the page.

4.  **Post-Processing and Sanitization**: All extracted outlines undergo a final cleaning pass to:
    * Remove any duplicate headings.
    * Correct the logical hierarchy (e.g., ensuring an H3 does not immediately follow an H1 by adjusting its level to H2).
    * Normalize text by removing extra whitespace and artifacts.

This principled, multi-strategy approach ensures high accuracy across a diverse range of PDF structures while strictly adhering to the hackathon's rule against hardcoding file-specific logic.

## Libraries Used

* **PyMuPDF (fitz)**: A high-performance Python library for all PDF manipulations. It is lightweight, fast, and self-contained, making it ideal for the resource constraints of the competition.

## How to Build and Run

1.  **Place PDFs**: Put your input PDF files into an `input` directory.

2.  **Build the Docker image**:
    ```bash
    docker build --platform linux/amd64 -t mysolutionname:somerandomidentifier .
    ```

3.  **Run the container**:
    * For Windows (CMD):
        ```bash
        docker run --rm -v "%CD%/input:/app/input" -v "%CD%/output:/app/output" --network none mysolutionname:somerandomidentifier
        ```
    * For macOS, Linux, or PowerShell:
        ```bash
        docker run --rm -v "$(pwd)/input:/app/input" -v "$(pwd)/output:/app/output" --network none mysolutionname:somerandomidentifier
        ```

The extracted JSON files will appear in the `output` directory.
