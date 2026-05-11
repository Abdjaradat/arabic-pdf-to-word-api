const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');
const pdfParse = require('pdf-parse');
const {
  Document, Packer, Paragraph, TextRun,
  HeadingLevel, AlignmentType, TabStopType, PageBreak
} = require('docx');
const { v4: uuidv4 } = require('uuid');

function extractWithPdftotext(inputPath) {
  try {
    const result = spawnSync('pdftotext', [
      '-layout',
      '-nopgbrk',
      '-enc', 'UTF-8',
      inputPath,
      '-'
    ], { timeout: 60000, maxBuffer: 50 * 1024 * 1024 });

    if (result.status === 0 && result.stdout && result.stdout.length > 0) {
      return { text: result.stdout.toString('utf-8'), method: 'pdftotext' };
    }
  } catch (e) {
    console.warn('pdftotext failed:', e.message);
  }
  return null;
}

function extractWithPdfParse(inputPath) {
  try {
    const pdfBuffer = fs.readFileSync(inputPath);
    return pdfParse(pdfBuffer).then(data => ({
      text: data.text,
      method: 'pdf-parse',
      numpages: data.numpages
    }));
  } catch (e) {
    console.warn('pdf-parse failed:', e.message);
    return null;
  }
}

function isArabicText(text) {
  const arabicPattern = /[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]/;
  let arabicCount = 0;
  const totalChars = text.replace(/\s/g, '').length;
  if (totalChars === 0) return false;
  for (const char of text) {
    if (arabicPattern.test(char)) arabicCount++;
  }
  return (arabicCount / totalChars) > 0.3;
}

function detectParagraphType(text, prevEmpty) {
  const trimmed = text.trim();
  if (!trimmed) return 'empty';
  if (trimmed.length < 60 && prevEmpty &&
      !trimmed.endsWith('.') && !trimmed.endsWith('؟') &&
      !trimmed.endsWith('!') && !trimmed.endsWith('،')) {
    return 'heading';
  }
  return 'body';
}

function createTextRun(text, isRtl, options = {}) {
  return new TextRun({
    text: text,
    font: isRtl ? 'Traditional Arabic' : 'Arial',
    size: options.size || 22,
    bold: options.bold || false,
    italics: options.italics || false,
    color: options.color || '000000',
    rtl: isRtl || false
  });
}

function textToDocxContent(text, isRtl) {
  const rawLines = text.split('\n');
  const blocks = [];
  let currentBlock = [];
  let prevEmpty = true;

  for (let i = 0; i < rawLines.length; i++) {
    const line = rawLines[i];
    if (!line.trim()) {
      if (currentBlock.length > 0) {
        blocks.push({ lines: currentBlock, type: detectParagraphType(currentBlock.join(' '), prevEmpty) });
        currentBlock = [];
      }
      prevEmpty = true;
      continue;
    }
    currentBlock.push(line.trimEnd());
    prevEmpty = false;
  }
  if (currentBlock.length > 0) {
    blocks.push({ lines: currentBlock, type: detectParagraphType(currentBlock.join(' '), prevEmpty) });
  }

  const children = [];

  children.push(
    new Paragraph({
      children: [createTextRun(
        isRtl ? 'تم التحويل بواسطة Arabic PDF To Word' : 'Converted by Arabic PDF To Word',
        isRtl, { size: 18, color: '888888' }
      )],
      alignment: isRtl ? AlignmentType.RIGHT : AlignmentType.LEFT,
      bidirectional: isRtl,
      spacing: { after: 400 }
    })
  );

  for (const block of blocks) {
    if (block.type === 'empty') continue;
    const text = block.lines.join(' ').trim();

    if (block.type === 'heading') {
      children.push(
        new Paragraph({
          children: [createTextRun(text, isRtl, { size: 28, bold: true })],
          heading: HeadingLevel.HEADING_1,
          alignment: isRtl ? AlignmentType.RIGHT : AlignmentType.LEFT,
          bidirectional: isRtl,
          spacing: { before: 300, after: 200 }
        })
      );
      continue;
    }

    const runs = [];
    for (const line of block.lines) {
      const trimmed = line.trimRight();
      if (!trimmed) continue;
      const isLineArabic = isArabicText(trimmed);
      runs.push(createTextRun(trimmed, isLineArabic || isRtl, {
        size: trimmed.length < 20 ? 24 : 22
      }));
    }
    if (runs.length === 0) continue;

    children.push(
      new Paragraph({
        children: runs,
        alignment: isRtl ? AlignmentType.RIGHT : AlignmentType.JUSTIFIED,
        bidirectional: isRtl,
        spacing: { after: 120, line: 360 },
        tabStops: [{ type: TabStopType.RIGHT, position: isRtl ? 9350 : 0 }]
      })
    );
  }

  children.push(
    new Paragraph({ children: [new PageBreak()], spacing: { before: 600 } })
  );
  children.push(
    new Paragraph({
      children: [createTextRun(
        isRtl ? '— نهاية المستند —' : '— End of Document —',
        isRtl, { size: 20, color: '999999' }
      )],
      alignment: AlignmentType.CENTER,
      bidirectional: isRtl,
      spacing: { before: 400 }
    })
  );

  return children;
}

async function convertPdfToWord(inputPath, outputDir, language = 'ara') {
  const isRtl = language === 'ara';
  const outputFileName = `${uuidv4()}.docx`;
  const outputPath = path.join(outputDir, outputFileName);

  let extracted = extractWithPdftotext(inputPath);
  let pageCount = 1;

  if (!extracted) {
    const pdfData = await extractWithPdfParse(inputPath);
    if (pdfData) {
      extracted = pdfData;
      pageCount = pdfData.numpages || 1;
    }
  }

  const text = extracted ? extracted.text : '(No text could be extracted from this PDF)';

  const children = textToDocxContent(text, isRtl);

  const doc = new Document({
    title: 'Converted Document',
    description: 'Converted from PDF to Word',
    styles: {
      default: {
        document: {
          run: { font: isRtl ? 'Traditional Arabic' : 'Arial', size: 22 },
          paragraph: {
            alignment: isRtl ? AlignmentType.RIGHT : AlignmentType.LEFT,
            bidirectional: isRtl,
            spacing: { line: 360 }
          }
        }
      }
    },
    sections: [{
      properties: {
        page: {
          margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 }
        }
      },
      children: children
    }]
  });

  const buffer = await Packer.toBuffer(doc);
  fs.writeFileSync(outputPath, buffer);

  return {
    outputPath,
    outputFileName,
    pageCount,
    textLength: text.length
  };
}

module.exports = { convertPdfToWord };