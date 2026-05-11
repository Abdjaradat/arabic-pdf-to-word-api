const fs = require('fs');
const path = require('path');
const pdfParse = require('pdf-parse');
const { Document, Packer, Paragraph, TextRun, HeadingLevel } = require('docx');
const { v4: uuidv4 } = require('uuid');

async function convertPdfToWord(inputPath, outputDir, language = 'ara') {
  const pdfBuffer = fs.readFileSync(inputPath);
  const pdfData = await pdfParse(pdfBuffer);

  const outputFileName = `${uuidv4()}.docx`;
  const outputPath = path.join(outputDir, outputFileName);

  const paragraphs = pdfData.text
    .split('\n')
    .filter(line => line.trim().length > 0)
    .map(line => {
      return new Paragraph({
        children: [
          new TextRun({
            text: line.trim(),
            size: 24,
            font: language === 'ara' ? 'Arial' : 'Arial'
          })
        ],
        spacing: { after: 200 }
      });
    });

  if (paragraphs.length === 0) {
    paragraphs.push(new Paragraph({
      children: [new TextRun({ text: '(No text content extracted from PDF)', size: 24 })],
      spacing: { after: 200 }
    }));
  }

  const doc = new Document({
    title: 'Converted Document',
    description: 'Converted from PDF to Word',
    sections: [{
      properties: {},
      children: paragraphs
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

module.exports = { convertPdfToWord };
