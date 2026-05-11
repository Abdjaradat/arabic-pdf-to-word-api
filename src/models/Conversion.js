const mongoose = require('mongoose');
const { v4: uuidv4 } = require('uuid');

const conversionSchema = new mongoose.Schema({
  conversionId: {
    type: String,
    default: () => uuidv4(),
    unique: true,
    index: true
  },
  userId: {
    type: mongoose.Schema.Types.ObjectId,
    ref: 'User',
    required: true,
    index: true
  },
  status: {
    type: String,
    enum: ['pending', 'processing', 'completed', 'failed'],
    default: 'pending'
  },
  originalFileName: String,
  originalFileSize: Number,
  outputFileName: String,
  outputFileSize: Number,
  pageCount: Number,
  ocrUsed: {
    type: Boolean,
    default: false
  },
  language: {
    type: String,
    default: 'ara'
  },
  errorMessage: String,
  progress: {
    type: Number,
    default: 0
  },
  originalFilePath: String,
  outputFilePath: String,
  completedAt: Date
}, {
  timestamps: true
});

conversionSchema.index({ createdAt: -1 });
conversionSchema.index({ status: 1, createdAt: -1 });

module.exports = mongoose.model('Conversion', conversionSchema);
