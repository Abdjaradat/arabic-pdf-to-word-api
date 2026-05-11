const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');
const pdfParse = require('pdf-parse');
const {
  Document, Packer, Paragraph, TextRun,
  HeadingLevel, AlignmentType, TabStopType, PageBreak
} = require('docx');
const { v4: uuidv4 } = require('uuid');

async function convertWithPython(inputPath, outputDir) {
  const scriptPath = path.join(__dirname, 'convert_pdf.py');
  if (!fs.existsSync(scriptPath)) return null;

  const pythonCommands = [
    '/opt/venv/bin/python3',
    '/opt/venv/bin/python',
    'python3',
    'python'
  ];

  for (const cmd of pythonCommands) {
    try {
      const result = spawnSync(cmd, [scriptPath, inputPath, outputDir], {
        timeout: 300000,
        maxBuffer: 50 * 1024 * 1024
      });

      if (result.status === 0 && result.stdout && result.stdout.length > 0) {
        try {
          const data = JSON.parse(result.stdout.toString().trim());
          if (data && !data.error) return data;
        } catch (e) {
          continue;
        }
      } else if (result.stderr && result.stderr.length > 0) {
        const stderr = result.stderr.toString();
        if (stderr.includes('No module named')) {
          console.warn(`Python module missing for ${cmd}, trying next`);
          continue;
        }
      }
    } catch (e) {
      continue;
    }
  }

  return null;
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
  if (trimmed.length < 50 && prevEmpty && !trimmed.endsWith('.') && !trimmed.endsWith('؟') && !trimmed.endsWith('!')) {
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

async function convertWithNode(inputPath, outputDir, language) {
  const pdfBuffer = fs.readFileSync(inputPath);
  const pdfData = await pdfParse(pdfBuffer);

  const outputFileName = `${uuidv4()}.docx`;
  const outputPath = path.join(outputDir, outputFileName);

  const isRtl = language === 'ara';

  const rawLines = pdfData.text.split('\n');
  const blocks = [];
  let currentBlock = [];
  let prevEmpty = true;

  for (let i = 0; i < rawLines.length; i++) {
    const line = rawLines[i].trim();
    if (!line) {
      if (currentBlock.length > 0) {
        blocks.push({ lines: currentBlock, type: detectParagraphType(currentBlock.join(' '), prevEmpty) });
        currentBlock = [];
      }
      prevEmpty = true;
      continue;
    }
    currentBlock.push(rawLines[i].trimEnd());
    prevEmpty = false;
  }
  if (currentBlock.length > 0) {
    blocks.push({ lines: currentBlock, type: detectParagraphType(currentBlock.join(' '), prevEmpty) });
  }

  const children = [];

  children.push(
    new Paragraph({
      children: [createTextRun(
        language === 'ara' ? 'تم التحويل بواسطة Arabic PDF To Word' : 'Converted by Arabic PDF To Word',
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
      const trimmed = line.trim();
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
        language === 'ara' ? '— نهاية المستند —' : '— End of Document —',
        isRtl, { size: 20, color: '999999' }
      )],
      alignment: AlignmentType.CENTER,
      bidirectional: isRtl,
      spacing: { before: 400 }
    })
  );

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
    pageCount: pdfData.numpages || 1,
    textLength: pdfData.text.length
  };
}

async function convertPdfToWord(inputPath, outputDir, language = 'ara') {
  // Try Python converter first for better quality
  try {
    const pyResult = await convertWithPython(inputPath, outputDir);
    if (pyResult && !pyResult.error) {
      console.log('Python conversion succeeded');
      return pyResult;
    }
    if (pyResult && pyResult.error) {
      console.warn('Python conversion error:', pyResult.error);
    }
  } catch (e) {
    console.warn('Python converter not available, falling back to Node.js:', e.message);
  }

  // Fall back to Node.js converter
  console.log('Using Node.js converter');
  return convertWithNode(inputPath, outputDir, language);
}

module.exports = { convertPdfToWord };