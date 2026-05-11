const express = require('express');
const path = require('path');
const fs = require('fs');
const auth = require('../middleware/auth');
const upload = require('../middleware/upload');
const Conversion = require('../models/Conversion');
const User = require('../models/User');
const { convertPdfToWord } = require('../services/pdfService');

const router = express.Router();

router.post('/upload', auth, (req, res) => {
  upload.single('file')(req, res, async (err) => {
    if (err) {
      if (err.code === 'LIMIT_FILE_SIZE') {
        return res.status(413).json({ error: 'File too large. Maximum size is 10MB.' });
      }
      return res.status(400).json({ error: err.message });
    }

    if (!req.file) {
      return res.status(400).json({ error: 'No file uploaded' });
    }

    try {
      const user = req.user;
      const now = new Date();
      const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate());

      if (!user.lastConversionDate || user.lastConversionDate < todayStart) {
        user.dailyConversionCount = 0;
      }

      const freeLimit = 5;
      if (!user.isPremium && user.dailyConversionCount >= freeLimit) {
        fs.unlinkSync(req.file.path);
        return res.status(429).json({ error: 'Daily limit reached. Upgrade to premium.' });
      }

      const conversion = new Conversion({
        userId: user._id,
        originalFileName: req.file.originalname,
        originalFileSize: req.file.size,
        originalFilePath: req.file.path,
        status: 'pending',
        language: req.body.language || 'ara'
      });
      await conversion.save();

      user.conversionCount += 1;
      user.dailyConversionCount += 1;
      user.lastConversionDate = now;
      await user.save();

      conversion.status = 'processing';
      conversion.progress = 10;
      await conversion.save();

      setImmediate(async () => {
        try {
          conversion.progress = 30;
          await conversion.save();

          const result = await convertPdfToWord(
            req.file.path,
            path.join(__dirname, '..', '..', 'uploads'),
            req.body.language || 'ara'
          );

          conversion.status = 'completed';
          conversion.progress = 100;
          conversion.outputFileName = result.outputFileName;
          conversion.outputFilePath = result.outputPath;
          conversion.pageCount = result.pageCount;
          conversion.completedAt = new Date();

          const stats = fs.statSync(result.outputPath);
          conversion.outputFileSize = stats.size;

          await conversion.save();
        } catch (convError) {
          console.error('Conversion error:', convError);
          conversion.status = 'failed';
          conversion.errorMessage = convError.message || 'Conversion failed';
          conversion.progress = 0;
          await conversion.save();
        }
      });

      res.status(201).json({
        id: conversion._id.toString(),
        conversion_id: conversion.conversionId,
        status: conversion.status,
        original_file_name: conversion.originalFileName,
        original_file_size: conversion.originalFileSize,
        page_count: conversion.pageCount,
        language: conversion.language,
        ocr_used: conversion.ocrUsed,
        created_at: conversion.createdAt,
        message: 'File uploaded successfully'
      });
    } catch (error) {
      console.error('Upload error:', error);
      res.status(500).json({ error: 'Upload failed' });
    }
  });
});

router.get('/status/:id', auth, async (req, res) => {
  try {
    const conversion = await Conversion.findOne({
      conversionId: req.params.id,
      userId: req.userId
    });

    if (!conversion) {
      return res.status(404).json({ error: 'Conversion not found' });
    }

    res.json(formatConversion(conversion));
  } catch (error) {
    console.error('Status error:', error);
    res.status(500).json({ error: 'Failed to get status' });
  }
});

router.get('/download/:id', auth, async (req, res) => {
  try {
    const conversion = await Conversion.findOne({
      conversionId: req.params.id,
      userId: req.userId
    });

    if (!conversion) {
      return res.status(404).json({ error: 'Conversion not found' });
    }

    if (conversion.status !== 'completed') {
      return res.status(400).json({ error: 'Conversion not completed yet' });
    }

    if (!conversion.outputFilePath || !fs.existsSync(conversion.outputFilePath)) {
      return res.status(404).json({ error: 'File not found' });
    }

    res.download(conversion.outputFilePath, conversion.outputFileName || 'converted.docx');
  } catch (error) {
    console.error('Download error:', error);
    res.status(500).json({ error: 'Download failed' });
  }
});

router.delete('/:id', auth, async (req, res) => {
  try {
    const conversion = await Conversion.findOne({
      conversionId: req.params.id,
      userId: req.userId
    });

    if (!conversion) {
      return res.status(404).json({ error: 'Conversion not found' });
    }

    if (conversion.originalFilePath && fs.existsSync(conversion.originalFilePath)) {
      fs.unlinkSync(conversion.originalFilePath);
    }
    if (conversion.outputFilePath && fs.existsSync(conversion.outputFilePath)) {
      fs.unlinkSync(conversion.outputFilePath);
    }

    await Conversion.deleteOne({ _id: conversion._id });

    res.json({ message: 'Conversion deleted successfully' });
  } catch (error) {
    console.error('Delete error:', error);
    res.status(500).json({ error: 'Delete failed' });
  }
});

router.get('/history', auth, async (req, res) => {
  try {
    const page = parseInt(req.query.page) || 1;
    const size = parseInt(req.query.size) || 20;
    const skip = (page - 1) * size;

    const [conversions, total] = await Promise.all([
      Conversion.find({ userId: req.userId })
        .sort({ createdAt: -1 })
        .skip(skip)
        .limit(size),
      Conversion.countDocuments({ userId: req.userId })
    ]);

    res.json({
      data: conversions.map(formatConversion),
      page,
      size,
      total,
      total_pages: Math.ceil(total / size),
      has_more: skip + size < total
    });
  } catch (error) {
    console.error('History error:', error);
    res.status(500).json({ error: 'Failed to get history' });
  }
});

router.get('/stats', auth, async (req, res) => {
  try {
    const user = req.user;
    const now = new Date();
    const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate());

    const [totalConversions, todayConversions] = await Promise.all([
      Conversion.countDocuments({ userId: req.userId }),
      Conversion.countDocuments({
        userId: req.userId,
        createdAt: { $gte: todayStart }
      })
    ]);

    const premiumConversions = await Conversion.countDocuments({
      userId: req.userId,
      createdAt: { $gte: todayStart }
    });

    const freeLimit = 5;
    const freeRemaining = user.isPremium ? null : Math.max(0, freeLimit - (user.dailyConversionCount || 0));

    res.json({
      total_conversions: totalConversions,
      today_conversions: todayConversions,
      storage_used: 0,
      premium_conversions: premiumConversions,
      free_conversions_remaining: freeRemaining,
      is_premium: user.isPremium
    });
  } catch (error) {
    console.error('Stats error:', error);
    res.status(500).json({ error: 'Failed to get stats' });
  }
});

function formatConversion(conversion) {
  return {
    id: conversion._id.toString(),
    conversion_id: conversion.conversionId,
    status: conversion.status,
    original_file_name: conversion.originalFileName,
    original_file_size: conversion.originalFileSize,
    output_file_name: conversion.outputFileName,
    output_file_size: conversion.outputFileSize,
    page_count: conversion.pageCount,
    ocr_used: conversion.ocrUsed,
    error_message: conversion.errorMessage,
    language: conversion.language,
    created_at: conversion.createdAt,
    completed_at: conversion.completedAt,
    progress: conversion.progress
  };
}

module.exports = router;
