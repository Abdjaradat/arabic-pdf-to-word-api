const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');
const pdfParse = require('pdf-parse');
const {
  Document, Packer, Paragraph, TextRun,
  AlignmentType, PageBreak
} = require('docx');
const { v4: uuidv4 } = require('uuid');

// ── Azure Document Intelligence (AI احترافي) ──
let azureClient = null;
async function getAzureClient() {
  if (azureClient) return azureClient;
  const endpoint = process.env.AZURE_DI_ENDPOINT;
  const key = process.env.AZURE_DI_KEY;
  if (!endpoint || !key) return null;
  try {
    const { DocumentAnalysisClient, AzureKeyCredential } = require('@azure/ai-form-recognizer');
    azureClient = new DocumentAnalysisClient(endpoint, new AzureKeyCredential(key));
    return azureClient;
  } catch (e) {
    console.warn('Azure SDK not available:', e.message);
    return null;
  }
}

async function convertWithAzure(inputPath, outputDir) {
  const client = await getAzureClient();
  if (!client) return null;

  try {
    const pdfBuffer = fs.readFileSync(inputPath);
    const poller = await client.beginAnalyzeDocument('prebuilt-layout', pdfBuffer);
    const result = await poller.pollUntilDone();

    const outputFileName = `${uuidv4()}.docx`;
    const outputPath = path.join(outputDir, outputFileName);

    const children = [];
    let pageCount = 0;

    if (result.pages) pageCount = result.pages.length;

    children.push(new Paragraph({
      children: [new TextRun({ text: 'Converted by Arabic PDF To Word AI', font: 'Arial', size: 18, color: '888888' })],
      spacing: { after: 400 }
    }));

    const isRtl = true;

    if (result.paragraphs) {
      for (const para of result.paragraphs) {
        const text = para.content?.trim();
        if (!text) continue;

        const hasArabic = /[\u0600-\u06FF]/.test(text);
        const runs = [new TextRun({
          text,
          font: hasArabic ? 'Traditional Arabic' : 'Arial',
          size: 22,
          rtl: hasArabic || isRtl
        })];

        children.push(new Paragraph({
          children: runs,
          alignment: hasArabic ? AlignmentType.RIGHT : AlignmentType.JUSTIFIED,
          bidirectional: hasArabic || isRtl,
          spacing: { after: 120, line: 360 }
        }));
      }
    }

    if (result.tables) {
      for (const table of result.tables) {
        if (!table.cells) continue;
        for (const cell of table.cells) {
          const text = cell.content?.trim();
          if (!text) continue;
          children.push(new Paragraph({
            children: [new TextRun({ text, font: 'Arial', size: 20 })],
            spacing: { after: 80 }
          }));
        }
      }
    }

    children.push(new Paragraph({ children: [new PageBreak()], spacing: { before: 600 } }));
    children.push(new Paragraph({
      children: [new TextRun({ text: '— End of Document —', font: 'Arial', size: 20, color: '999999' })],
      alignment: AlignmentType.CENTER,
      spacing: { before: 400 }
    }));

    const doc = new Document({
      sections: [{
        properties: { page: { margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 } } },
        children
      }]
    });

    const buffer = await Packer.toBuffer(doc);
    fs.writeFileSync(outputPath, buffer);

    console.log('Azure Document Intelligence conversion succeeded');
    return { outputPath, outputFileName, pageCount, textLength: pdfBuffer.length, method: 'azure-ai' };
  } catch (e) {
    console.warn('Azure conversion failed:', e.message);
    return null;
  }
}

// ── Google Gemini API (مجاني وقوي، عربي متصل بشكل صحيح) ──
async function convertWithGemini(inputPath, outputDir) {
  const apiKey = process.env.GEMINI_API_KEY;
  if (!apiKey) return null;

  try {
    const { GoogleGenerativeAI, GoogleAIFileManager } = require('@google/generative-ai');
    const fileManager = new GoogleAIFileManager(apiKey);

    // Upload PDF to Gemini File API
    const uploadResult = await fileManager.uploadFile(inputPath, {
      mimeType: 'application/pdf',
      displayName: path.basename(inputPath),
    });

    // Wait for file processing
    let file = await fileManager.getFile(uploadResult.file.name);
    let attempts = 0;
    while (file.state === 'PROCESSING' && attempts < 30) {
      await new Promise(resolve => setTimeout(resolve, 2000));
      file = await fileManager.getFile(uploadResult.file.name);
      attempts++;
    }
    if (file.state !== 'ACTIVE') {
      console.warn('Gemini file processing timed out or failed');
      return null;
    }

    const genAI = new GoogleGenerativeAI(apiKey);
    const model = genAI.getGenerativeModel({ model: 'gemini-2.0-flash' });

    const result = await model.generateContent([
      { fileData: { mimeType: file.mimeType, fileUri: file.uri } },
      { text: 'Extract ALL text from this PDF exactly as it appears, preserving the original layout, paragraphs, line breaks, and sections. If the document contains Arabic text, make sure Arabic letters are properly connected and shaped (الحروف العربية متصلة بشكل صحيح وليست منفصلة). Return the complete text as plain text with original paragraph structure preserved.' }
    ]);

    const text = result.response.text();

    const outputFileName = `${uuidv4()}.docx`;
    const outputPath$1 = path.join(outputDir, outputFileName);
    const children = textToDocxContent(text, true);
    const doc = new Document({
      sections: [{ properties: { page: { margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 } } }, children }]
    });
    const buffer = await Packer.toBuffer(doc);
    fs.writeFileSync(outputPath$1, buffer);

    console.log('Gemini AI conversion succeeded');
    return { outputPath: outputPath$1, outputFileName, pageCount: countPdfPages(inputPath), textLength: text.length, method: 'gemini-ai' };
  } catch (e) {
    console.warn('Gemini conversion failed:', e.message);
    return null;
  }
}

// ── LibreOffice (يحافظ على التنسيق) ──
function convertWithLibreOffice(inputPath, outputDir) {
  try {
    const outputFileName = `${uuidv4()}.docx`;
    const outputPath = path.join(outputDir, outputFileName);

    const result = spawnSync('soffice', [
      '--headless', '--norestore', '--nofirststartwizard',
      '--convert-to', 'docx', '--outdir', outputDir, inputPath
    ], { timeout: 120000 });

    if (result.status === 0) {
      const files = fs.readdirSync(outputDir)
        .filter(f => f.endsWith('.docx'))
        .sort((a, b) => fs.statSync(path.join(outputDir, b)).mtimeMs - fs.statSync(path.join(outputDir, a)).mtimeMs);

      if (files.length > 0) {
        const actualOutput = path.join(outputDir, files[0]);
        if (actualOutput !== outputPath) fs.renameSync(actualOutput, outputPath);
        const stats = fs.statSync(outputPath);
        const pageCount = countPdfPages(inputPath);
        console.log('LibreOffice conversion succeeded');
        return { outputPath, outputFileName, pageCount, textLength: stats.size, method: 'libreoffice' };
      }
    }
  } catch (e) {
    console.warn('LibreOffice failed:', e.message);
  }
  return null;
}

// ── pdftotext (استخراج النص العربي) ──
function extractWithPdftotext(inputPath) {
  try {
    const result = spawnSync('pdftotext', [
      '-layout', '-nopgbrk', '-enc', 'UTF-8', inputPath, '-'
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
  const arabicPattern = /[\u0600-\u06FF\u0750-\u077F]/;
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
  for (let i = 0; i < rawLines.length; i++) {
    const line = rawLines[i];
    if (!line.trim()) {
      if (currentBlock.length > 0) { blocks.push(currentBlock); currentBlock = []; }
      continue;
    }
    currentBlock.push(line.trimEnd());
  }
  if (currentBlock.length > 0) blocks.push(currentBlock);

  const children = [];
  children.push(new Paragraph({
    children: [new TextRun({ text: isRtl ? 'تم التحويل بواسطة Arabic PDF To Word' : 'Converted by Arabic PDF To Word', font: isRtl ? 'Traditional Arabic' : 'Arial', size: 18, color: '888888', rtl: isRtl || false })],
    alignment: isRtl ? AlignmentType.RIGHT : AlignmentType.LEFT, bidirectional: isRtl, spacing: { after: 400 }
  }));

  for (const block of blocks) {
    const runs = [];
    for (const line of block) {
      const trimmed = line.trimRight();
      if (!trimmed) continue;
      const isLineArabic = isArabicText(trimmed);
      runs.push(new TextRun({ text: trimmed, font: isLineArabic || isRtl ? 'Traditional Arabic' : 'Arial', size: trimmed.length < 20 ? 24 : 22, rtl: isLineArabic || isRtl || false }));
    }
    if (runs.length === 0) continue;
    children.push(new Paragraph({ children: runs, alignment: isRtl ? AlignmentType.RIGHT : AlignmentType.JUSTIFIED, bidirectional: isRtl, spacing: { after: 120, line: 360 } }));
  }

  children.push(new Paragraph({ children: [new PageBreak()], spacing: { before: 600 } }));
  children.push(new Paragraph({ children: [new TextRun({ text: isRtl ? '— نهاية المستند —' : '— End of Document —', font: isRtl ? 'Traditional Arabic' : 'Arial', size: 20, color: '999999', rtl: isRtl || false })], alignment: AlignmentType.CENTER, bidirectional: isRtl, spacing: { before: 400 } }));
  return children;
}

async function convertWithNode(inputPath, outputDir, isRtl) {
  const text = extractWithPdftotext(inputPath);
  if (!text) {
    const pdfBuffer = fs.readFileSync(inputPath);
    const pdfData = await pdfParse(pdfBuffer);
    const outputFileName = `${uuidv4()}.docx`;
    const outputPath = path.join(outputDir, outputFileName);
    const children = textToDocxContent(pdfData.text, isRtl);
    const doc = new Document({ sections: [{ properties: { page: { margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 } } }, children }] });
    const buffer = await Packer.toBuffer(doc);
    fs.writeFileSync(outputPath, buffer);
    return { outputPath, outputFileName, pageCount: pdfData.numpages || 1, textLength: pdfData.text.length, method: 'pdf-parse' };
  }

  const outputFileName = `${uuidv4()}.docx`;
  const outputPath = path.join(outputDir, outputFileName);
  const children = textToDocxContent(text, isRtl);
  const pageCount = countPdfPages(inputPath);
  const doc = new Document({
    styles: { default: { document: { run: { font: isRtl ? 'Traditional Arabic' : 'Arial', size: 22 }, paragraph: { alignment: isRtl ? AlignmentType.RIGHT : AlignmentType.LEFT, bidirectional: isRtl, spacing: { line: 360 } } } } },
    sections: [{ properties: { page: { margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 } } }, children }]
  });
  const buffer = await Packer.toBuffer(doc);
  fs.writeFileSync(outputPath, buffer);
  return { outputPath, outputFileName, pageCount, textLength: text.length, method: 'pdftotext' };
}

async function convertPdfToWord(inputPath, outputDir, language = 'ara') {
  const isRtl = language === 'ara';

  // 1. Azure AI (إذا كان مفتاح API موجود) — أدق وأحترافي
  const azure = await convertWithAzure(inputPath, outputDir);
  if (azure) return azure;

  // 2. Google Gemini (إذا كان مفتاح API موجود) — عربي متصل بشكل صحيح، مجاني وقوي
  const gemini = await convertWithGemini(inputPath, outputDir);
  if (gemini) return gemini;

  // 3. LibreOffice — يحافظ على التنسيق
  const lo = convertWithLibreOffice(inputPath, outputDir);
  if (lo) return lo;

  // 4. pdftotext — استخراج النص العربي (fallback)
  console.log('Using Node.js converter (pdftotext → docx)');
  return convertWithNode(inputPath, outputDir, isRtl);
}

module.exports = { convertPdfToWord };