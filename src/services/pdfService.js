const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');
const pdfParse = require('pdf-parse');
const {
  Document, Packer, Paragraph, TextRun,
  HeadingLevel, AlignmentType, TabStopType, PageBreak
} = require('docx');
const { v4: uuidv4 } = require('uuid');

function convertWithLibreOffice(inputPath, outputDir) {
  try {
    const outputFileName = `${uuidv4()}.docx`;
    const outputPath = path.join(outputDir, outputFileName);

    const result = spawnSync('soffice', [
      '--headless',
      '--norestore',
      '--nofirststartwizard',
      '--convert-to', 'docx',
      '--outdir', outputDir,
      inputPath
    ], { timeout: 120000 });

    if (result.status === 0) {
      const files = fs.readdirSync(outputDir)
        .filter(f => f.endsWith('.docx'))
        .sort((a, b) => fs.statSync(path.join(outputDir, b)).mtimeMs - fs.statSync(path.join(outputDir, a)).mtimeMs);

      if (files.length > 0) {
        const actualOutput = path.join(outputDir, files[0]);
        if (actualOutput !== outputPath) {
          fs.renameSync(actualOutput, outputPath);
        }
        const stats = fs.statSync(outputPath);
        return { outputPath, outputFileName, method: 'libreoffice', fileSize: stats.size };
      }
    }
  } catch (e) {
    console.warn('LibreOffice failed:', e.message);
  }
  return null;
}

function extractWithPdftotext(inputPath) {
  try {
    const result = spawnSync('pdftotext', [
      '-layout', '-nopgbrk', '-enc', 'UTF-8',
      inputPath, '-'
    ], { timeout: 60000, maxBuffer: 50 * 1024 * 1024 });

    if (result.status === 0 && result.stdout && result.stdout.length > 0) {
      return result.stdout.toString('utf-8');
    }
  } catch (e) {
    console.warn('pdftotext failed:', e.message);
  }
  return null;
}

function countPdfPages(inputPath) {
  try {
    const result = spawnSync('pdfinfo', [inputPath], { timeout: 10000 });
    if (result.status === 0) {
      const match = result.stdout.toString().match(/Pages:\s*(\d+)/i);
      if (match) return parseInt(match[1]);
    }
  } catch (_) {}
  return 1;
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

function textToDocxContent(text, isRtl) {
  const rawLines = text.split('\n');
  const blocks = [];
  let currentBlock = [];
  let prevEmpty = true;

  for (let i = 0; i < rawLines.length; i++) {
    const line = rawLines[i];
    if (!line.trim()) {
      if (currentBlock.length > 0) {
        blocks.push({ lines: currentBlock, type: 'body' });
        currentBlock = [];
      }
      prevEmpty = true;
      continue;
    }
    currentBlock.push(line.trimEnd());
    prevEmpty = false;
  }
  if (currentBlock.length > 0) {
    blocks.push({ lines: currentBlock, type: 'body' });
  }

  const children = [];

  children.push(
    new Paragraph({
      children: [new TextRun({
        text: isRtl ? 'تم التحويل بواسطة Arabic PDF To Word' : 'Converted by Arabic PDF To Word',
        font: isRtl ? 'Traditional Arabic' : 'Arial',
        size: 18, color: '888888',
        rtl: isRtl || false
      })],
      alignment: isRtl ? AlignmentType.RIGHT : AlignmentType.LEFT,
      bidirectional: isRtl,
      spacing: { after: 400 }
    })
  );

  for (const block of blocks) {
    const runs = [];
    for (const line of block.lines) {
      const trimmed = line.trimRight();
      if (!trimmed) continue;
      const isLineArabic = isArabicText(trimmed);
      runs.push(new TextRun({
        text: trimmed,
        font: isLineArabic || isRtl ? 'Traditional Arabic' : 'Arial',
        size: trimmed.length < 20 ? 24 : 22,
        rtl: isLineArabic || isRtl || false
      }));
    }
    if (runs.length === 0) continue;

    children.push(
      new Paragraph({
        children: runs,
        alignment: isRtl ? AlignmentType.RIGHT : AlignmentType.JUSTIFIED,
        bidirectional: isRtl,
        spacing: { after: 120, line: 360 }
      })
    );
  }

  children.push(new Paragraph({ children: [new PageBreak()], spacing: { before: 600 } }));
  children.push(new Paragraph({
    children: [new TextRun({
      text: isRtl ? '— نهاية المستند —' : '— End of Document —',
      font: isRtl ? 'Traditional Arabic' : 'Arial',
      size: 20, color: '999999',
      rtl: isRtl || false
    })],
    alignment: AlignmentType.CENTER,
    bidirectional: isRtl,
    spacing: { before: 400 }
  }));

  return children;
}

async function convertWithNode(inputPath, outputDir, isRtl) {
  const text = extractWithPdftotext(inputPath);

  if (!text) {
    try {
      const pdfBuffer = fs.readFileSync(inputPath);
      const pdfData = await pdfParse(pdfBuffer);
      const outputFileName = `${uuidv4()}.docx`;
      const outputPath = path.join(outputDir, outputFileName);
      const children = textToDocxContent(pdfData.text, isRtl);

      const doc = new Document({
        sections: [{
          properties: {
            page: { margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 } }
          },
          children
        }]
      });

      const buffer = await Packer.toBuffer(doc);
      fs.writeFileSync(outputPath, buffer);
      return {
        outputPath, outputFileName,
        pageCount: pdfData.numpages || 1,
        textLength: pdfData.text.length,
        method: 'pdf-parse'
      };
    } catch (e) {
      throw new Error('All conversion methods failed');
    }
  }

  const outputFileName = `${uuidv4()}.docx`;
  const outputPath = path.join(outputDir, outputFileName);
  const children = textToDocxContent(text, isRtl);
  const pageCount = countPdfPages(inputPath);

  const doc = new Document({
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
        page: { margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 } }
      },
      children
    }]
  });

  const buffer = await Packer.toBuffer(doc);
  fs.writeFileSync(outputPath, buffer);

  return {
    outputPath, outputFileName,
    pageCount,
    textLength: text.length,
    method: 'pdftotext'
  };
}

async function convertPdfToWord(inputPath, outputDir, language = 'ara') {
  const isRtl = language === 'ara';

  // 1. Try LibreOffice first — best layout preservation
  const lo = convertWithLibreOffice(inputPath, outputDir);
  if (lo) {
    const pageCount = countPdfPages(inputPath);
    console.log('LibreOffice conversion succeeded');
    return {
      outputPath: lo.outputPath,
      outputFileName: lo.outputFileName,
      pageCount,
      textLength: lo.fileSize,
      method: 'libreoffice'
    };
  }

  // 2. Fall back to Node.js (pdftotext → pdf-parse)
  console.log('LibreOffice not available, using Node.js converter');
  return convertWithNode(inputPath, outputDir, isRtl);
}

module.exports = { convertPdfToWord };