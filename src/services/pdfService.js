// RSWS Algorithm: Read -> Store -> Write -> Style
// CONFIDENTIAL — Proprietary Intellectual Property
// The RSWS engine, including its document reconstruction pipeline, iterative correction
// workflow, layout recovery logic, visual comparison system, and adaptive refinement
// methodology, constitutes proprietary intellectual property.
// Unauthorized disclosure, publication, reproduction, reverse engineering, redistribution,
// or commercial usage is strictly prohibited.

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

// ── Google Gemini API (عبر REST - أسرع وأدق للعربي) ──
async function convertWithGemini(inputPath, outputDir) {
  const apiKey = process.env.GEMINI_API_KEY;
  if (!apiKey) return null;

  try {
    // Convert ALL pages of PDF to PNG images using pdftoppm
    const tempPrefix = path.join(outputDir, `gemini_${uuidv4()}`);
    const pngResult = spawnSync('pdftoppm', [
      '-png', '-r', '300', inputPath, tempPrefix
    ], { timeout: 120000 });

    if (pngResult.status !== 0) return null;

    const imageFiles = fs.readdirSync(outputDir)
      .filter(f => f.startsWith(path.basename(tempPrefix)) && f.endsWith('.png'))
      .sort();

    if (imageFiles.length === 0) return null;

    // Build parts array: one image per page + final text prompt
    const parts = [];
    for (const imgFile of imageFiles) {
      const imgPath = path.join(outputDir, imgFile);
      const imgData = fs.readFileSync(imgPath).toString('base64');
      parts.push({ inline_data: { mime_type: 'image/png', data: imgData } });
    }
    parts.push({ text: 'Extract ALL text from these images preserving paragraphs, line breaks, and sections. Arabic text MUST have properly connected letters (الحروف العربية متصلة وليست منفصلة). Return ONLY the extracted text in order, no explanations.' });

    // Call Gemini REST API
    const https = require('https');
    const url = new URL(`https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key=${apiKey}`);

    const text = await new Promise((resolve, reject) => {
      const req = https.request({
        hostname: 'generativelanguage.googleapis.com',
        path: url.pathname + url.search,
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
      }, (res) => {
        let data = '';
        res.on('data', chunk => data += chunk);
        res.on('end', () => {
          try {
            const parsed = JSON.parse(data);
            const extracted = parsed?.candidates?.[0]?.content?.parts?.map(p => p.text).join('\n') || '';
            resolve(extracted);
          } catch (e) { reject(e); }
        });
      });
      req.on('error', reject);
      req.write(JSON.stringify({ contents: [{ parts }] }));
      req.end();
    });

    // Cleanup temp images
    for (const imgFile of imageFiles) {
      try { fs.unlinkSync(path.join(outputDir, imgFile)); } catch (_) {}
    }

    if (!text) return null;

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

// ── RSWS Algorithm: Read → Store → Write → Style ──
// اختراع: Read PDF, Store words+formatting, Write word-by-word into Word, Style each word
function rswsReadPdf(inputPath) {
  // Read: استخرج النص من PDF
  try {
    const result = spawnSync('pdftotext', [
      '-layout', '-nopgbrk', '-enc', 'UTF-8', inputPath, '-'
    ], { timeout: 60000, maxBuffer: 50 * 1024 * 1024 });
    if (result.status === 0 && result.stdout && result.stdout.length > 0) {
      return { text: result.stdout.toString('utf-8'), method: 'pdftotext' };
    }
  } catch (_) {}
  return null;
}

function detectWordFont(word) {
  return isArabicText(word) ? 'Traditional Arabic' : 'Arial';
}

function detectWordSize(word) {
  const len = word.replace(/\s/g, '').length;
  if (len <= 2) return 20;
  if (len <= 6) return 22;
  if (len <= 12) return 26;
  return 28;
}

async function rswsStoreText(rawText) {
  const paragraphs = [];
  const rawParagraphs = rawText.split('\n');
  let currentPara = [];

  for (const line of rawParagraphs) {
    const trimmed = line.trim();
    if (!trimmed) {
      if (currentPara.length > 0) {
        paragraphs.push(currentPara.join(' ').replace(/\s+/g, ' '));
        currentPara = [];
      }
      continue;
    }
    currentPara.push(trimmed);
  }
  if (currentPara.length > 0) {
    paragraphs.push(currentPara.join(' ').replace(/\s+/g, ' '));
  }

  const stored = [];
  for (const para of paragraphs) {
    if (!para) continue;
    const words = para.split(/\s+/).filter(w => w.length > 0);
    const paraArabic = isArabicText(para);
    const wordInfos = words.map(w => ({
      text: w,
      font: detectWordFont(w),
      size: detectWordSize(w),
      bold: false,
      italic: false,
      has_arabic: isArabicText(w),
    }));
    stored.push({
      text: para,
      words: wordInfos,
      alignment: paraArabic ? AlignmentType.RIGHT : AlignmentType.JUSTIFIED,
      has_arabic: paraArabic,
    });
  }
  return stored;
}

async function rswsWriteStyle(stored, outputPath) {
  // Write + Style: اكتب كلمة كلمة ونسقها
  const children = [];

  children.push(new Paragraph({
    children: [new TextRun({
      text: 'تم التحويل بواسطة Arabic PDF To Word (RSWS)',
      font: 'Traditional Arabic', size: 16, color: '888888',
      rtl: true
    })],
    alignment: AlignmentType.RIGHT,
    bidirectional: true,
    spacing: { after: 400 }
  }));

  for (const para of stored) {
    const runs = [];
    for (const word of para.words) {
      runs.push(new TextRun({
        text: word.text + ' ',
        font: word.font,
        size: word.size,
        bold: word.bold,
        italic: word.italic,
        rtl: word.has_arabic || para.has_arabic,
      }));
    }
    children.push(new Paragraph({
      children: runs,
      alignment: para.alignment,
      bidirectional: para.has_arabic,
      spacing: { after: 120, line: 360 }
    }));
  }

  children.push(new Paragraph({
    children: [new TextRun({
      text: '— نهاية المستند —',
      font: 'Traditional Arabic', size: 16, color: '999999', rtl: true
    })],
    alignment: AlignmentType.CENTER,
    bidirectional: true,
    spacing: { before: 400 }
  }));

  const doc = new Document({
    sections: [{
      properties: {
        page: {
          margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 }
        }
      },
      children
    }]
  });

  const buffer = await Packer.toBuffer(doc);
  fs.writeFileSync(outputPath, buffer);
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

async function convertWithRSWS(inputPath, outputDir) {
  console.log('RSWS: Reading PDF...');
  // Step 1: Read
  const readResult = rswsReadPdf(inputPath);
  if (!readResult) return null;

  console.log('RSWS: Storing words...');
  // Step 2: Store
  const stored = await rswsStoreText(readResult.text);
  if (stored.length === 0) return null;

  const outputFileName = `${uuidv4()}.docx`;
  const outputPath = path.join(outputDir, outputFileName);
  const wordCount = stored.reduce((sum, p) => sum + p.words.length, 0);

  console.log(`RSWS: Writing ${wordCount} words into Word...`);
  // Step 3+4: Write & Style
  await rswsWriteStyle(stored, outputPath);

  const pageCount = countPdfPages(inputPath);
  const stats = fs.statSync(outputPath);

  console.log(`RSWS: Done → ${outputFileName}`);
  return {
    outputPath,
    outputFileName,
    pageCount,
    textLength: readResult.text.length,
    method: 'rsws',
    outputFileSize: stats.size,
  };
}

// ── Recursive RSWS: RSWS → Word → PDF → RSWS → ... × N ──
function convertWithPythonRecursive(inputPath, outputDir, iterations = 100) {
  try {
    const scriptPath = path.join(__dirname, 'convert_pdf.py');
    if (!fs.existsSync(scriptPath)) return null;

    console.log(`Python recursive RSWS: ${iterations} iterations...`);
    const result = spawnSync('python3', [
      scriptPath, '--recursive', inputPath, outputDir, String(iterations)
    ], {
      timeout: Math.min(iterations * 10000, 120000),
      maxBuffer: 100 * 1024 * 1024
    });

    if (result.status !== 0) {
      const result2 = spawnSync('python', [
        scriptPath, '--recursive', inputPath, outputDir, String(iterations)
      ], {
        timeout: 600000,
        maxBuffer: 100 * 1024 * 1024
      });
      if (result2.status !== 0) return null;
      try {
        const parsed = JSON.parse(result2.stdout.toString());
        if (parsed.error) return null;
        parsed.method = 'rsws_recursive';
        return parsed;
      } catch (_) { return null; }
    }

    try {
      const parsed = JSON.parse(result.stdout.toString());
      if (parsed.error) return null;
      parsed.method = 'rsws_recursive';
      return parsed;
    } catch (_) { return null; }
  } catch (e) {
    console.warn('Python recursive RSWS failed:', e.message);
    return null;
  }
}

// ── Python PyMuPDF converter (بالنسبة للبيئة اللي فيها Python) ──
function convertWithPython(inputPath, outputDir) {
  try {
    const scriptPath = path.join(__dirname, 'convert_pdf.py');
    if (!fs.existsSync(scriptPath)) return null;

    const result = spawnSync('python3', [scriptPath, inputPath, outputDir], {
      timeout: 600000,
      maxBuffer: 100 * 1024 * 1024
    });

    if (result.status !== 0) {
      const result2 = spawnSync('python', [scriptPath, inputPath, outputDir], {
        timeout: 600000,
        maxBuffer: 100 * 1024 * 1024
      });
      if (result2.status !== 0) return null;
      try {
        const parsed = JSON.parse(result2.stdout.toString());
        if (parsed.error) return null;
        return parsed;
      } catch (_) { return null; }
    }

    try {
      const parsed = JSON.parse(result.stdout.toString());
      if (parsed.error) return null;
      return parsed;
    } catch (_) { return null; }
  } catch (e) {
    console.warn('Python converter failed:', e.message);
    return null;
  }
}

async function convertPdfToWord(inputPath, outputDir, language = 'ara', quality = 'normal') {
  const isRtl = language === 'ara';

  // ثلاث مستويات:
  //   normal  = RSWS مرة واحدة   (مجاناً)
  //   high    = RSWS مرتين        (مشاركة 3 مرات)
  //   premium = RSWS 3 مرات       (مشاركة 3 مرات)
  if (quality === 'premium') {
    console.log('PREMIUM: Running recursive RSWS (3 iterations)...');
    const recResult = convertWithPythonRecursive(inputPath, outputDir, 3);
    if (recResult) return recResult;
  }

  if (quality === 'high') {
    console.log('HIGH: Running recursive RSWS (2 iterations)...');
    const recResult = convertWithPythonRecursive(inputPath, outputDir, 2);
    if (recResult) return recResult;
  }

  // 1. Python PyMuPDF RSWS (سريع — 2-5 ثواني)
  console.log('Trying Python RSWS converter (PyMuPDF)...');
  const pyResult = convertWithPython(inputPath, outputDir);
  if (pyResult) return pyResult;

  // 2. Node.js RSWS (pdftotext)
  console.log('Trying Node.js RSWS converter (pdftotext)...');
  const rsws = await convertWithRSWS(inputPath, outputDir);
  if (rsws) return rsws;

  // 3. Azure AI
  const azure = await convertWithAzure(inputPath, outputDir);
  if (azure) return azure;

  // 4. Google Gemini
  const gemini = await convertWithGemini(inputPath, outputDir);
  if (gemini) return gemini;

  // 5. LibreOffice
  const lo = convertWithLibreOffice(inputPath, outputDir);
  if (lo) return lo;

  // 6. pdftotext (fallback)
  console.log('Using Node.js converter (pdftotext → docx)');
  return convertWithNode(inputPath, outputDir, isRtl);
}

module.exports = { convertPdfToWord };