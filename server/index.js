// Environment variables load karne ke liye dotenv ka use karte hain
require('dotenv').config();
const express = require('express');
const cors = require('cors');
const mongoose = require('mongoose');
const axios = require('axios');
const multer = require('multer');
const FormData = require('form-data');
const fs = require('fs');

const app = express();
const PORT = process.env.PORT || 5000;
const PYTHON_ENGINE_URL = process.env.PYTHON_ENGINE_URL || 'http://localhost:8000';

app.use(cors());
app.use(express.json({ limit: '50mb' }));
app.use(express.urlencoded({ limit: '50mb', extended: true }));

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
  runId: { type: String, required: true, index: true },
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

const AuditEventSchema = new mongoose.Schema({
  event_id: { type: String, required: true, unique: true },
  run_id: { type: String, index: true },
  dataset_id: { type: String },
  exception_id: { type: String, index: true },
  transaction_id: { type: String, index: true },
  event_type: { type: String, required: true },
  actor_type: { type: String },
  actor_id: { type: String },
  actor_name: { type: String },
  actor_role: { type: String },
  previous_status: { type: String },
  new_status: { type: String },
  action: { type: String },
  decision: { type: String },
  reason: { type: String },
  evidence_reference: { type: Object },
  timestamp: { type: Date, default: Date.now },
  metadata: { type: Object }
});

const AuditEvent = mongoose.model('AuditEvent', AuditEventSchema);// ==========================================
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
    const runId = `RUN-${Date.now()}`;
    
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

    res.status(500).json({
      success: false,
      message: 'Failed to process reconciliation',
      error: error.message
    });
  }
});

// Configure Multer for temp file storage
const upload = multer({ 
  dest: 'uploads/',
  limits: { fileSize: 10 * 1024 * 1024 } // 10MB limit
});

app.post('/api/validate-data', upload.fields([
  { name: 'bank_file', maxCount: 1 },
  { name: 'settle_file', maxCount: 1 },
  { name: 'ledger_file', maxCount: 1 }
]), async (req, res) => {
  try {
    const dataset_id = req.body.dataset_id;
    if (!dataset_id) {
      return res.status(400).json({ success: false, message: 'dataset_id is required' });
    }

    const form = new FormData();
    if (req.files['bank_file']) form.append('bank_file', fs.createReadStream(req.files['bank_file'][0].path), req.files['bank_file'][0].originalname);
    if (req.files['settle_file']) form.append('settle_file', fs.createReadStream(req.files['settle_file'][0].path), req.files['settle_file'][0].originalname);
    if (req.files['ledger_file']) form.append('ledger_file', fs.createReadStream(req.files['ledger_file'][0].path), req.files['ledger_file'][0].originalname);

    console.log(`🔄 Validating files via Python Engine for dataset: ${dataset_id}...`);
    
    const pythonResponse = await axios.post(`${PYTHON_ENGINE_URL}/validate`, form, {
      headers: { ...form.getHeaders() }
    });

    // Clean up temp files
    Object.keys(req.files).forEach(key => {
      req.files[key].forEach(file => {
        fs.unlink(file.path, err => {
          if (err) console.error("Failed to delete temp file:", file.path);
        });
      });
    });

    res.json({
      success: true,
      dataset_id,
      ...pythonResponse.data
    });

  } catch (error) {
    console.error('❌ Validation API Error:', error.message);
    if (req.files) {
      Object.keys(req.files).forEach(key => {
        req.files[key].forEach(file => fs.unlink(file.path, () => {}));
      });
    }
    res.status(500).json({ success: false, message: 'Failed to validate data', error: error.message });
  }
});

app.post('/api/upload-and-reconcile', upload.fields([
  { name: 'bank_file', maxCount: 1 },
  { name: 'settle_file', maxCount: 1 },
  { name: 'ledger_file', maxCount: 1 }
]), async (req, res) => {
  try {
    const dataset_id = req.body.dataset_id;
    const exclude_invalid = req.body.exclude_invalid === 'true' || req.body.exclude_invalid === true;
    if (!dataset_id) {
      return res.status(400).json({ success: false, message: 'dataset_id is required' });
    }

    const form = new FormData();
    form.append('dataset_id', dataset_id);
    form.append('exclude_invalid', exclude_invalid.toString());

    if (req.files['bank_file']) {
      form.append('bank_file', fs.createReadStream(req.files['bank_file'][0].path), req.files['bank_file'][0].originalname);
    }
    if (req.files['settle_file']) {
      form.append('settle_file', fs.createReadStream(req.files['settle_file'][0].path), req.files['settle_file'][0].originalname);
    }
    if (req.files['ledger_file']) {
      form.append('ledger_file', fs.createReadStream(req.files['ledger_file'][0].path), req.files['ledger_file'][0].originalname);
    }

    console.log(`🔄 Forwarding uploaded files to Python Engine for dataset: ${dataset_id}...`);
    
    const pythonResponse = await axios.post(`${PYTHON_ENGINE_URL}/upload-and-reconcile`, form, {
      headers: {
        ...form.getHeaders()
      }
    });

    const data = pythonResponse.data;

    // Clean up temp files
    if (req.files) {
        Object.keys(req.files).forEach(key => {
          req.files[key].forEach(file => {
            fs.unlink(file.path, err => {
              if (err) console.error("Failed to delete temp file:", file.path);
            });
          });
        });
    }

    if (data.status === 'error') {
      return res.status(500).json({ 
        success: false, 
        message: 'Python Engine generated an error', 
        error: data.message 
      });
    }

    const runId = `RUN-${Date.now()}`;
    
    // Attempt to save to MongoDB, but gracefully continue if MongoDB is just a mock
    try {
      const newResult = new ReconciliationResult({
        runId: runId,
        summary: data.summary,
        fully_matched: data.fully_matched,
        fuzzy_matched: data.fuzzy_matched,
        needs_review: data.needs_review,
        unmatched: data.unmatched
      });
      await newResult.save();
      console.log(`✅ Reconciliation saved with Run ID: ${runId}`);
    } catch (dbErr) {
      console.log('⚠️ MongoDB save skipped (likely missing fields). Run ID:', runId);
    }

    res.json({
      success: true,
      runId: runId,
      dataset_id: data.dataset_id,
      data_quality: data.data_quality,
      data: data
    });

  } catch (error) {
    console.error('❌ Upload Reconciliation API Error:', error.message);
    
    // Clean up temp files on error
    if (req.files) {
      Object.keys(req.files).forEach(key => {
        req.files[key].forEach(file => {
          fs.unlink(file.path, () => {});
        });
      });
    }

    res.status(500).json({
      success: false,
      message: 'Failed to process custom reconciliation',
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
      success: false,
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
      success: false,
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
      success: false,
      message: 'Failed to communicate with AI'
    });
  }
});


// ==========================================
// 4. AUDIT API ROUTES
// ==========================================

app.post('/api/audit/event', async (req, res) => {
  try {
    const payload = req.body;
    // Idempotency check
    const existing = await AuditEvent.findOne({ event_id: payload.event_id });
    if (existing) {
      return res.status(200).json({ success: true, message: 'Event already recorded (idempotent)', event: existing });
    }
    
    const newEvent = new AuditEvent(payload);
    await newEvent.save();
    res.status(201).json({ success: true, event: newEvent });
  } catch (error) {
    console.error('❌ Audit Event Save Error:', error.message);
    res.status(500).json({ success: false, message: 'Failed to save audit event', error: error.message });
  }
});

app.get('/api/audit/run/:runId', async (req, res) => {
  try {
    const events = await AuditEvent.find({ run_id: req.params.runId }).sort({ timestamp: 1 });
    res.json(events);
  } catch (error) {
    res.status(500).json({ success: false, error: error.message });
  }
});

app.get('/api/audit/exception/:exceptionId', async (req, res) => {
  try {
    const events = await AuditEvent.find({ exception_id: req.params.exceptionId }).sort({ timestamp: 1 });
    res.json(events);
  } catch (error) {
    res.status(500).json({ success: false, error: error.message });
  }
});

app.get('/api/audit/metrics', async (req, res) => {
  try {
    const totalEvents = await AuditEvent.countDocuments();
    const aiActions = await AuditEvent.countDocuments({ actor_type: 'AI' });
    const systemActions = await AuditEvent.countDocuments({ actor_type: 'SYSTEM' });
    const humanActions = await AuditEvent.countDocuments({ actor_type: 'HUMAN' });
    const humanOverrides = await AuditEvent.countDocuments({ action: 'Override' });
    
    res.json({
      totalEvents, aiActions, systemActions, humanActions, humanOverrides
    });
  } catch (error) {
    res.status(500).json({ success: false, error: error.message });
  }
});

// ==========================================
// 5. START SERVER
// ==========================================

app.post('/api/exceptions/resolve', async (req, res) => {
  try {
    const payload = req.body;
    const pythonResponse = await axios.post(`${PYTHON_ENGINE_URL}/exceptions/resolve`, payload);
    
    // Update MongoDB if runId is provided
    if (payload.runId) {
      const runId = payload.runId;
      const excId = payload.exception_id;
      
      const record = await ReconciliationResult.findOne({ runId: runId });
      if (record) {
        let updated = false;
        ['fuzzy_matched', 'needs_review', 'unmatched'].forEach(category => {
          if (record[category]) {
            const idx = record[category].findIndex(e => e.group_id === excId);
            if (idx !== -1) {
              if (!record[category][idx].investigation_state) {
                record[category][idx].investigation_state = {};
              }
              record[category][idx].investigation_state.resolution = payload.final_status;
              
              if (payload.notes) {
                if (!record[category][idx].investigation_state.notes) {
                  record[category][idx].investigation_state.notes = [];
                }
                record[category][idx].investigation_state.notes.push({
                   author: payload.actor_role || 'REVIEWER',
                   timestamp: new Date().toISOString(),
                   message: payload.notes
                });
              }
              // Mark the array as modified so Mongoose saves the nested changes
              record.markModified(category);
              updated = true;
            }
          }
        });
        if (updated) {
          await record.save();
        }
      }
    }
    
    res.json(pythonResponse.data);
  } catch (error) {
    console.error('❌ Resolve Exception API Error:', error.message);
    res.status(500).json({ success: false, message: 'Failed to resolve exception', error: error.message });
  }
});

// Start Server
app.listen(PORT, () => {
  console.log(`Server running on http://localhost:${PORT}`);
  console.log(`Python Engine expected at ${PYTHON_ENGINE_URL}`);
});
