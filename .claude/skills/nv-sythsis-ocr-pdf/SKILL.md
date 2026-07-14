```markdown
# nv-sythsis-ocr-pdf Development Patterns

> Auto-generated skill from repository analysis

## Overview
This skill covers the development patterns and conventions found in the `nv-sythsis-ocr-pdf` Python repository. The codebase focuses on OCR (Optical Character Recognition) synthesis for PDFs, providing utilities to process and extract text from PDF documents. This guide documents the coding style, file structure, and common workflows to help contributors maintain consistency and efficiency.

## Coding Conventions

### File Naming
- Use **camelCase** for file names.
  - Example: `extractText.py`, `pdfProcessor.py`

### Imports
- Use **relative imports** within modules.
  - Example:
    ```python
    from .utils import cleanText
    ```

### Exports
- Use **named exports** (explicitly export functions/classes).
  - Example:
    ```python
    def extractTextFromPDF(pdf_path):
        # function body
        return text
    ```

### Commit Patterns
- Commit messages are **freeform** with no strict prefix, averaging 42 characters.
  - Example:
    ```
    add support for multi-page PDF extraction
    ```

## Workflows

### PDF OCR Extraction
**Trigger:** When you need to extract text from a PDF using OCR.
**Command:** `/extract-ocr`

1. Place your target PDF file in the designated input directory.
2. Run the main OCR extraction script:
    ```bash
    python extractText.py input/yourfile.pdf output/yourfile.txt
    ```
3. Review the output text file for accuracy.

### Adding a New Utility Function
**Trigger:** When you want to add a helper function to the codebase.
**Command:** `/add-utility`

1. Create a new file using camelCase naming in the appropriate module.
2. Write your utility function and use relative imports as needed.
    ```python
    # In cleanText.py
    def cleanText(text):
        # cleaning logic
        return cleaned_text
    ```
3. Import your function in other modules using relative imports.

### Running Tests
**Trigger:** When you want to verify code correctness.
**Command:** `/run-tests`

1. Locate test files matching the `*.test.*` pattern.
2. Run tests using your preferred Python test runner (e.g., `pytest` or `unittest`).
    ```bash
    python -m unittest discover -p "*.test.*"
    ```
3. Review test output and fix any failing tests.

## Testing Patterns

- Test files follow the `*.test.*` naming pattern (e.g., `extractText.test.py`).
- The testing framework is not explicitly specified; use standard Python test runners.
- Tests should be placed alongside or near the modules they test.

**Example test file:**
```python
# extractText.test.py
import unittest
from .extractText import extractTextFromPDF

class TestExtractText(unittest.TestCase):
    def test_extract_simple_pdf(self):
        result = extractTextFromPDF('sample.pdf')
        self.assertIn('Expected Text', result)
```

## Commands
| Command         | Purpose                                      |
|-----------------|----------------------------------------------|
| /extract-ocr    | Extract text from a PDF using OCR            |
| /add-utility    | Add a new utility function to the codebase   |
| /run-tests      | Run all test files matching *.test.* pattern |
```
