// Environment variables load karne ke liye dotenv ka use karte hain
require('dotenv').config();
const express = require('express');
const cors = require('cors');
const mongoose = require('mongoose');
const axios = require('axios');

const app = express();
const PORT = process.env.PORT || 5000;
const PYTHON_ENGINE_URL = process.env.PYTHON_ENGINE_URL || 'http://localhost:8000';

app.use(cors());
app.use(express.json());

// ==========================================
// 1. MONGODB CONNECTION
// ==========================================
const MONGODB_URI = process.env.MONGODB_URI || 'mongodb://localhost:27017/finance_reconciliation';

mongoose.connect(MONGODB_URI)
  .then(() => console.log('✅ Connected to MongoDB successfully'))
  .catch((err) => console.error('❌ MongoDB connection error:', err));

// ==========================================
// 2. MONGOOSE SCHEMA & MODEL
// ==========================================
const ReconciliationResultSchema = new mongoose.Schema({
  runId: { type: String, required: true },
  timestamp: { type: Date, default: Date.now },
  summary: {
    total_records: Number,
    fully_matched: Number,
    fuzzy_matched: Number,
    needs_review: Number,
    unmatched: Number,
    match_rate_percent: Number
  },
  fully_matched: Array,
  fuzzy_matched: Array,
  needs_review: Array,
  unmatched: Array
});

const ReconciliationResult = mongoose.model('ReconciliationResult', ReconciliationResultSchema);

// ==========================================
// 3. API ROUTES
// ==========================================

// Basic health check route
app.get('/test', (req, res) => {
  res.json({ status: "ok", message: "Express server is running perfectly!" });
});

// Route: Python engine ko trigger karna aur Data save karna
app.post('/api/reconcile', async (req, res) => {
  try {
    console.log('🔄 Calling Python FastAPI Engine...');
    
    // Axios se Python backend ko call karte hain
    const pythonResponse = await axios.post(`${PYTHON_ENGINE_URL}/reconcile`);
    const data = pythonResponse.data;
    
    // Agar Python engine ne khud koi error throw kiya ho
    if (data.status === 'error') {
      return res.status(500).json({ 
        success: false, 
        message: 'Python Engine generated an error', 
        error: data.message 
      });
    }

    // Run ID generate karte hain (timestamp ke aadhar par)
    const runId = `REC-${Date.now()}`;
    
    // MongoDB me save karne ke liye Document banate hain
    const newResult = new ReconciliationResult({
      runId: runId,
      summary: data.summary,
      fully_matched: data.fully_matched,
      fuzzy_matched: data.fuzzy_matched,
      needs_review: data.needs_review,
      unmatched: data.unmatched
    });

    // Database me save
    await newResult.save();
    console.log(`✅ Reconciliation saved with Run ID: ${runId}`);

    // Frontend ko response wapas bhejte hain
    res.json({
      success: true,
      runId: runId,
      data: data
    });

  } catch (error) {
    console.error('❌ Reconciliation API Error:', error.message);
    
    // Proper Error Handling (agar Python engine down ho)
    if (error.code === 'ECONNREFUSED') {
      return res.status(503).json({
        success: false,
        message: 'Python Engine (FastAPI) is down or unreachable. Please ensure it is running on port 8000.'
      });
    }

    // Other Generic errors
    res.status(500).json({
      success: false,
      message: 'Failed to process reconciliation',
      error: error.message
    });
  }
});

// Route: Pichle saare runs ki list nikalne ke liye
app.get('/api/reconcile/history', async (req, res) => {
  try {
    // Database se history fetch karte hain (Sirf runId, timestamp, aur summary select karenge fast response ke liye)
    const history = await ReconciliationResult.find()
      .select('runId timestamp summary')
      .sort({ timestamp: -1 }); // Naye waale pehle (descending order)
      
    res.json({
      success: true,
      count: history.length,
      history: history
    });
  } catch (error) {
    console.error('❌ History API Error:', error);
    res.status(500).json({
      success: false,
      message: 'Failed to fetch reconciliation history',
      error: error.message
    });
  }
});

// Route: Evaluation karne ke liye
app.post('/api/evaluate', async (req, res) => {
  try {
    const pythonResponse = await axios.post(`${PYTHON_ENGINE_URL}/evaluate`, req.body);
    res.json(pythonResponse.data);
  } catch (error) {
    console.error('❌ Evaluation API Error:', error.message);
    res.status(500).json({
      status: "error",
      message: 'Failed to evaluate reconciliation data'
    });
  }
});

// Route: Forecast karne ke liye
app.post('/api/forecast', async (req, res) => {
  try {
    const pythonResponse = await axios.post(`${PYTHON_ENGINE_URL}/forecast`, req.body);
    res.json(pythonResponse.data);
  } catch (error) {
    console.error('❌ Forecast API Error:', error.message);
    res.status(500).json({
      status: "error",
      message: 'Failed to forecast cash flow'
    });
  }
});

// Route: AI se chat karne ke liye
app.post('/api/ask', async (req, res) => {
  try {
    const pythonResponse = await axios.post(`${PYTHON_ENGINE_URL}/ask`, req.body);
    res.json(pythonResponse.data);
  } catch (error) {
    console.error('❌ Ask API Error:', error.message);
    res.status(500).json({
      status: "error",
      message: 'Failed to communicate with AI'
    });
  }
});

// ==========================================
// 4. START SERVER
// ==========================================
app.listen(PORT, () => {
  console.log(`🚀 Server is running on port ${PORT}`);
});
