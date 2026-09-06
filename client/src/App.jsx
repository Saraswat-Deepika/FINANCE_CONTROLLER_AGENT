import React, { useState } from 'react';
import axios from 'axios';
import { BarChart, Bar, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import './App.css';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:5000';

function App() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [selectedException, setSelectedException] = useState(null);
  const [evalData, setEvalData] = useState(null);
  const [evalError, setEvalError] = useState(null);
  const [forecastData, setForecastData] = useState(null);
  const [forecastError, setForecastError] = useState(null);
  
  // Data Ingestion States
  const [currentUserRole, setCurrentUserRole] = useState('REVIEWER');
  const [datasetMode, setDatasetMode] = useState('demo'); // 'demo' or 'upload'
  const [files, setFiles] = useState({ bank: null, settle: null, ledger: null });
  const [dataQuality, setDataQuality] = useState(null);
  const [datasetId, setDatasetId] = useState('');
  const [isValidationLoading, setIsValidationLoading] = useState(false);
  const [validationResult, setValidationResult] = useState(null);
  const [excludeInvalid, setExcludeInvalid] = useState(false);
  const [progressState, setProgressState] = useState('');
  const [runId, setRunId] = useState('');

  // Chat States
  const [chatHistory, setChatHistory] = useState([]);
  const [chatInput, setChatInput] = useState('');
  const [isChatLoading, setIsChatLoading] = useState(false);
  const [isActionLoading, setIsActionLoading] = useState(false);
  const [activeAction, setActiveAction] = useState(null);
  const [actionInput, setActionInput] = useState('');
  const [actionCategory, setActionCategory] = useState('');
  const [overrideSelection, setOverrideSelection] = useState('');
  const [toastMessage, setToastMessage] = useState(null);

  const showToast = (msg) => {
    setToastMessage(msg);
    setTimeout(() => setToastMessage(null), 3000);
  };

  
  const suggestedQuestions = [
    "What's our current cash position?",
    "Show unresolved high-value exceptions.",
    "Why is today's cash forecast lower?",
    "What is our reconciliation match rate?",
    "Which exceptions need human review?",
    "How many AI resolutions were approved?",
    "Show the biggest cash risks."
  ];
  
  // Filter States
  const [filterType, setFilterType] = useState('All');
  const [filterSource, setFilterSource] = useState('All');
  const [searchQuery, setSearchQuery] = useState('');
  const [sortConfig, setSortConfig] = useState({ key: 'priority', direction: 'desc' });
  const [selectedExceptions, setSelectedExceptions] = useState(new Set());
  const [auditTimeline, setAuditTimeline] = useState([]);
  const [auditMetrics, setAuditMetrics] = useState(null);

  const closeModal = () => setSelectedException(null);

  const handleSelectException = async (exp) => {
    setSelectedException(exp);
    setAuditTimeline([]);
    if (exp) {
        try {
            const res = await axios.get(`${API_BASE_URL}/api/audit/exception/${exp.group_id}`);
            setAuditTimeline(res.data);
        } catch (err) {
            console.error("Failed to fetch audit timeline", err);
        }
    }
  };
  
  const loadAuditMetrics = async () => {
      try {
          const res = await axios.get(`${API_BASE_URL}/api/audit/metrics`);
          setAuditMetrics(res.data);
      } catch (err) {
          console.error("Failed to load audit metrics", err);
      }
  };


  const handleSort = (key) => {
    let direction = 'asc';
    if (sortConfig.key === key && sortConfig.direction === 'asc') {
      direction = 'desc';
    }
    setSortConfig({ key, direction });
  };


  
  const handleResolutionAction = async (exception, action, reason, notes = null, custom_final_status = null) => {
    if (isActionLoading) return;
    setIsActionLoading(true);
    try {
        let final_status = custom_final_status || 'NEEDS_REVIEW';
        if (!custom_final_status) {
            if (action === 'Approve' || action === 'Accept') final_status = 'Resolved - Approved';
            else if (action === 'Reject') final_status = 'Resolved - Rejected';
            else if (action === 'Valid Difference') final_status = 'Resolved - Explainable Difference';
            else if (action === 'Escalate') final_status = 'Escalated - Pending Senior Review';
            else if (action === 'Request Info') final_status = 'Pending - Info Requested';
            else if (action === 'Manual Match') final_status = 'Resolved - Manual Override';
            else if (action === 'Override') final_status = 'Resolved - Manual Override';
        }
        
      const payload = {
        exception_id: exception.group_id,
        transaction_id: exception.investigation_state?.transaction_id || 'UNKNOWN',
        action: action,
        previous_status: exception.investigation_state?.resolution || 'UNKNOWN',
        final_status: final_status,
        reason: reason || '',
        actor_id: 'user_123',
        actor_role: currentUserRole,
        runId: runId,
        notes: notes
      };
      await axios.post(`${API_BASE_URL}/api/exceptions/resolve`, payload);
      
      // Update local state and remove from queue
      const newData = { ...data };
      let removed = false;
      ['fuzzy_matched', 'needs_review'].forEach(category => {
        if (newData[category]) {
          const originalLength = newData[category].length;
          // For status-changing actions (not Add Note), remove from active lists
          if (action !== 'Add Note') {
              newData[category] = newData[category].filter(e => e.group_id !== exception.group_id);
              if (newData[category].length < originalLength) removed = true;
          } else {
              const idx = newData[category].findIndex(e => e.group_id === exception.group_id);
              if (idx !== -1) {
                  if (!newData[category][idx].investigation_state) newData[category][idx].investigation_state = {};
                  newData[category][idx].investigation_state.resolution = payload.final_status;
              }
          }
        }
      });
      setData(newData);
      
      if (action !== 'Add Note') {
         showToast(`Marked as ${final_status}`);
         setSelectedException(null);
         setActiveAction(null);
         setActionInput('');
         setActionCategory('');
         setOverrideSelection('');
      } else {
         showToast("Note added successfully");
         if (selectedException && selectedException.group_id === exception.group_id) {
             handleSelectException({...selectedException, investigation_state: {...selectedException.investigation_state, resolution: payload.final_status}});
         }
      }
      loadAuditMetrics();
    } catch (err) {
      alert("Failed to save action: " + err.message);
    } finally {
      setIsActionLoading(false);
    }
  };

  const clearDataset = () => {
    setData(null);
    setEvalData(null);
    setForecastData(null);
    setChatHistory([]);
    setDataQuality(null);
    setError(null);
    setValidationResult(null);
    setProgressState('');
    setExcludeInvalid(false);
    if (datasetMode === 'upload') {
        // preserve files if they just want to re-run, but clear results
    }
  };

  const handleModeSwitch = (mode) => {
    if (mode !== datasetMode) {
      setDatasetMode(mode);
      setFiles({ bank: null, settle: null, ledger: null });
      setData(null);
      setEvalData(null);
      setForecastData(null);
      setChatHistory([]);
      setDataQuality(null);
      setError(null);
      setValidationResult(null);
      setProgressState('');
      setExcludeInvalid(false);
    }
  };

  const handleFileChange = (source, file) => {
    setFiles(prev => ({ ...prev, [source]: file }));
    // Invalidate stale data when new file is uploaded
    if (data) {
      clearDataset();
    }
  };

    const validateData = async () => {
    if (!files.bank && !files.settle && !files.ledger) {
      setError("Please upload at least one file to validate.");
      return;
    }
    setIsValidationLoading(true);
    setError(null);
    setValidationResult(null);
    const dId = `DATA-${Date.now()}`;
    setDatasetId(dId);

    const formData = new FormData();
    formData.append('dataset_id', dId);
    if (files.bank) formData.append('bank_file', files.bank);
    if (files.settle) formData.append('settle_file', files.settle);
    if (files.ledger) formData.append('ledger_file', files.ledger);

    try {
      const response = await axios.post(`${API_BASE_URL}/api/validate-data`, formData, {
        headers: { 'Content-Type': 'multipart/form-data' }
      });
      if (response.data.success) {
        setValidationResult(response.data);
      } else {
        setError("Validation failed: " + response.data.message);
      }
    } catch (err) {
      setError(err.response?.data?.message || err.message || 'An error occurred during validation');
    } finally {
      setIsValidationLoading(false);
    }
  };

  const runReconciliation = async () => {
    setLoading(true);
    setError(null);
    setEvalData(null);
    setEvalError(null);
    setProgressState('Preparing data...');
    try {
      let response;
      if (datasetMode === 'demo') {
        setProgressState('Validating sources...');
        await new Promise(r => setTimeout(r, 500));
        setProgressState('Normalizing records...');
        await new Promise(r => setTimeout(r, 500));
        setProgressState('Finding candidate matches...');
        response = await axios.post(`${API_BASE_URL}/api/reconcile`);
      } else {
        if (!datasetId || !validationResult) {
          throw new Error("Please validate data first.");
        }
        setProgressState('Preparing data...');
        const formData = new FormData();
        formData.append('dataset_id', datasetId);
        formData.append('exclude_invalid', excludeInvalid);
        if (files.bank) formData.append('bank_file', files.bank);
        if (files.settle) formData.append('settle_file', files.settle);
        if (files.ledger) formData.append('ledger_file', files.ledger);
        
        setProgressState('Validating and Normalizing...');
        response = await axios.post(`${API_BASE_URL}/api/upload-and-reconcile`, formData, {
          headers: { 'Content-Type': 'multipart/form-data' }
        });
      }

      setProgressState('Calculating metrics...');
      if (response.data.success) {
        setRunId(response.data.runId);
        setProgressState('Generating exceptions...');
        setData(response.data.data);
        if (response.data.data_quality) {
          setDataQuality(response.data.data_quality);
        }
        
        // Chain the evaluation call
        try {
          const evalResponse = await axios.post(`${API_BASE_URL}/api/evaluate`, { ...response.data.data, run_id: response.data.runId, dataset_id: response.data.dataset_id });
          if (evalResponse.data && evalResponse.data.overall_accuracy !== undefined) {
            setEvalData(evalResponse.data);
          } else {
            setEvalError('Evaluation data unavailable');
          }
        } catch (e) {
          setEvalError('Evaluation data unavailable');
        }
        
        // Chain the forecast call
        try {
          const payload = {
             fully_matched: response.data.data.fully_matched || [],
             fuzzy_matched: response.data.data.fuzzy_matched || [],
             needs_review: response.data.data.needs_review || [],
             unmatched: response.data.data.unmatched || [],
             config: { minimum_safe_cash: 50000.0 },
             run_id: response.data.runId,
             dataset_id: response.data.dataset_id
          };

          const forecastResponse = await axios.post(`${API_BASE_URL}/api/forecast`, payload);
          
          if (forecastResponse.data && forecastResponse.data.forecast) {
            setForecastData({
              mode: 'new',
              data: forecastResponse.data.forecast
            });
          } else {
            throw new Error('Forecast failed');
          }
        } catch (e) {
          console.error("Forecast error:", e);
          setForecastError('Failed to generate cash forecast');
        }
      }
    } catch (err) {
      setError(
        err.response?.data?.message || err.message || 'An error occurred during reconciliation'
      );
    } finally {
      setLoading(false);
      setProgressState('');
    }
  };

  const getChartData = () => {
    if (!data) return [];
    return [
      {
        name: 'Matched',
        value: data.summary.fully_matched,
        fill: '#10b981' // Green
      },
      {
        name: 'Fuzzy',
        value: data.summary.fuzzy_matched,
        fill: '#f59e0b' // Yellow
      },
      {
        name: 'Review',
        value: data.summary.needs_review || 0,
        fill: '#f97316' // Orange
      },
      {
        name: 'Unmatched',
        value: data.summary.unmatched,
        fill: '#ef4444' // Red
      }
    ];
  };

  
  const getMasterList = () => {
    if (!data) return [];
    const extractFields = (item, typeStr) => ({
      id: item.group_id,
      type: typeStr,
      source: item.missing_sources && item.missing_sources.length < 3 ? 'Partial Sources' : (item.missing_sources ? 'Single Source' : 'Multiple (Bank/Settle/Ledger)'),
      date: item.evidence?.date?.bank || item.bank?.date || item.settlement?.date || item.ledger?.date || 'N/A',
      amount: item.evidence?.amount?.bank || item.bank?.amount || item.settlement?.amount || item.ledger?.amount || 'N/A',
      reason: item.investigation_state?.root_cause || item.ai_reason || item.recommendation || 'Low confidence match',
      confidence: item.investigation_state?.confidence !== undefined ? item.investigation_state.confidence * 100 : (item.confidence_percentage || 0),
      resolution: item.investigation_state?.resolution || 'PENDING',
      priority: item.investigation_state?.priority || 'LOW',
      age: item.investigation_state?.age || 0,
      raw: item
    });

    const fuzzy = (data.fuzzy_matched || []).map(item => extractFields(item, 'Fuzzy Matched'));
    const needsReview = (data.needs_review || []).map(item => extractFields(item, item.status === 'PARTIAL_MATCH' ? 'Partial Match' : (item.status === 'DUPLICATE_SUSPECTED' ? 'Duplicate Suspected' : 'Needs Review')));
    const unmatched = (data.unmatched || []).map(item => extractFields(item, 'Unmatched'));
    
    return [...fuzzy, ...needsReview, ...unmatched];
  };

  const getFilteredList = () => {
    let list = getMasterList();
    if (filterType !== 'All') list = list.filter(item => item.type === filterType);
    if (filterSource !== 'All') {
      list = list.filter(item => {
        if (filterSource === 'Multiple') return item.source.startsWith('Multiple');
        if (filterSource === 'Bank Statement') return item.source === 'bank_statement';
        if (filterSource === 'Settlement') return item.source === 'settlement';
        if (filterSource === 'Ledger') return item.source === 'ledger';
        return true;
      });
    }
    if (searchQuery.trim() !== '') {
      const q = searchQuery.toLowerCase();
      list = list.filter(item => String(item.amount).toLowerCase().includes(q) || String(item.date).toLowerCase().includes(q) || String(item.id).toLowerCase().includes(q));
    }
    
    list.sort((a, b) => {
      let aVal = a[sortConfig.key];
      let bVal = b[sortConfig.key];
      if (sortConfig.key === 'priority') {
        const pMap = { 'CRITICAL': 4, 'HIGH': 3, 'MEDIUM': 2, 'LOW': 1 };
        aVal = pMap[aVal] || 0;
        bVal = pMap[bVal] || 0;
      }
      if (sortConfig.key === 'amount') {
        aVal = parseFloat(aVal) || 0;
        bVal = parseFloat(bVal) || 0;
      }
      if (aVal < bVal) return sortConfig.direction === 'asc' ? -1 : 1;
      if (aVal > bVal) return sortConfig.direction === 'asc' ? 1 : -1;
      return 0;
    });
    return list;
  };


  const handleAskAI = async (question) => {
    if (!question.trim() || !data) return;
    
    // Add user message
    const newHistory = [...chatHistory, { role: 'user', text: question }];
    setChatHistory(newHistory);
    setChatInput('');
    setIsChatLoading(true);
    
    try {
      // Pre-filter transaction specific queries
      const allExceptions = [...(data.fuzzy_matched||[]), ...(data.needs_review||[]), ...(data.unmatched||[])];
      let specificTransaction = null;
      
      const idMatch = question.match(/[A-Z0-9]{5,}/i) || question.match(/TXN-\d+|UTR-\w+|REF-\w+/i);
      if (idMatch) {
          const id = idMatch[0].toUpperCase();
          specificTransaction = allExceptions.find(ex => 
              ex.id?.toUpperCase() === id || 
              ex.group_id?.toUpperCase() === id || 
              ex.investigation_state?.transaction_id?.toUpperCase() === id ||
              ex.bank?.utr?.toUpperCase() === id ||
              ex.settlement?.id?.toUpperCase() === id ||
              ex.ledger?.id?.toUpperCase() === id
          );
      }

      const payload = {
        question: question,
        context_data: {
          summary: data.summary,
          evaluation: evalData || null,
          fuzzy_matched: data.fuzzy_matched || [],
          needs_review: data.needs_review || [],
          unmatched: data.unmatched || [],
          forecast: forecastData?.data || null,
          audit_metrics: auditMetrics || null,
          top_exceptions: allExceptions.filter(e => e.investigation_state?.priority === 'CRITICAL').slice(0, 5),
          specific_transaction: specificTransaction
        }
      };
      
      const response = await axios.post(`${API_BASE_URL}/api/ask`, payload);
      
      if (response.data && response.data.status === 'success') {
        setChatHistory([...newHistory, { role: 'ai', text: response.data.answer }]);
      } else {
        setChatHistory([...newHistory, { role: 'ai', text: "Sorry, I couldn't process that right now" }]);
      }
    } catch (e) {
      setChatHistory([...newHistory, { role: 'ai', text: "Sorry, I couldn't process that right now" }]);
    } finally {
      setIsChatLoading(false);
    }
  };

  const downloadCSV = () => {
    if (!data) return;
    
    const exceptions = getFilteredList();
    const dateStr = new Date().toISOString().split('T')[0];
    
    let csvContent = `Reconciliation Report - ${dateStr}\n`;
    csvContent += `Dataset ID:,${datasetMode === 'upload' ? datasetId : 'DEMO-DATA'}\n`;
    csvContent += `Run ID:,${runId || 'N/A'}\n`;
    
    if (dataQuality) {
      csvContent += `\n--- Data Quality ---\n`;
      Object.keys(dataQuality).forEach(src => {
        csvContent += `${src} Valid:,${dataQuality[src].valid_records}\n`;
        csvContent += `${src} Invalid:,${dataQuality[src].invalid_records}\n`;
        csvContent += `${src} Duplicates:,${dataQuality[src].duplicates}\n`;
      });
      csvContent += `\n`;
    }

    csvContent += `--- Reconciliation Summary ---\n`;
    csvContent += `Total Records:,${data.summary.total_records}\n`;
    csvContent += `Fully Matched:,${data.summary.fully_matched}\n`;
    csvContent += `Fuzzy Matched:,${data.summary.fuzzy_matched}\n`;
    csvContent += `Needs Review:,${data.summary.needs_review || 0}\n`;
    csvContent += `Unmatched:,${data.summary.unmatched}\n`;
    csvContent += `Match Rate:,${data.summary.match_rate_percent}%\n\n`;
    
    csvContent += "Type,Source,Date,Amount,Confidence Score,AI Reason\n";
    
    exceptions.forEach(row => {
      const escapeCSV = (val) => {
        if (val === null || val === undefined) return '';
        const str = String(val);
        if (str.includes(',') || str.includes('"') || str.includes('\n')) {
          return `"${str.replace(/"/g, '""')}"`;
        }
        return str;
      };
      
      const rowString = [
        escapeCSV(row.type),
        escapeCSV(row.source),
        escapeCSV(row.date),
        escapeCSV(row.amount),
        escapeCSV(row.confidence ? Math.round(row.confidence) + '%' : ''),
        escapeCSV(row.reason)
      ].join(",");
      
      csvContent += rowString + "\n";
    });
    
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.setAttribute("href", url);
    link.setAttribute("download", `reconciliation_report_${dateStr}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  return (
    <div className="app-layout">
      {toastMessage && (
        <div style={{
          position: 'fixed', top: '20px', left: '50%', transform: 'translateX(-50%)',
          background: '#10b981', color: 'white', padding: '12px 24px', borderRadius: '8px',
          boxShadow: '0 4px 6px rgba(0,0,0,0.1)', zIndex: 9999, fontWeight: 'bold'
        }}>
          {toastMessage}
        </div>
      )}
      <aside className="sidebar">
        <h1 className="sidebar-title">AI Finance Controller</h1>
        <div className="sidebar-section">
          <span className="sidebar-label">Dataset</span>
          <div className="dataset-toggle" style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem', padding: '0 0.5rem' }}>
            <button 
              onClick={() => handleModeSwitch('demo')}
              style={{
                background: datasetMode === 'demo' ? '#2563eb' : 'transparent',
                color: 'white',
                border: datasetMode === 'demo' ? '1px solid #2563eb' : '1px solid rgba(255,255,255,0.3)',
                padding: '0.875rem 1rem',
                fontSize: '0.95rem',
                fontWeight: '600',
                borderRadius: '8px',
                cursor: 'pointer',
                transition: 'all 0.2s ease',
                width: '100%',
                textAlign: 'center'
              }}
              onMouseEnter={(e) => { if(datasetMode !== 'demo') e.currentTarget.style.background = 'rgba(255,255,255,0.1)'; }}
              onMouseLeave={(e) => { if(datasetMode !== 'demo') e.currentTarget.style.background = 'transparent'; }}
            >
              Demo Synthetic Data
            </button>
            <button 
              onClick={() => handleModeSwitch('upload')}
              style={{
                background: datasetMode === 'upload' ? '#2563eb' : 'transparent',
                color: 'white',
                border: datasetMode === 'upload' ? '1px solid #2563eb' : '1px solid rgba(255,255,255,0.3)',
                padding: '0.875rem 1rem',
                fontSize: '0.95rem',
                fontWeight: '600',
                borderRadius: '8px',
                cursor: 'pointer',
                transition: 'all 0.2s ease',
                width: '100%',
                textAlign: 'center'
              }}
              onMouseEnter={(e) => { if(datasetMode !== 'upload') e.currentTarget.style.background = 'rgba(255,255,255,0.1)'; }}
              onMouseLeave={(e) => { if(datasetMode !== 'upload') e.currentTarget.style.background = 'transparent'; }}
            >
              Upload Your Own Data
            </button>
          </div>
        </div>
        
        <div className="sidebar-section">
          <span className="sidebar-label">Operations</span>
          <select value={currentUserRole} onChange={e => setCurrentUserRole(e.target.value)}>
            <option value="ADMIN">Role: Admin</option>
            <option value="REVIEWER">Role: Reviewer</option>
            <option value="VIEWER">Role: Viewer</option>
          </select>
          <button 
            className="btn-primary" 
            onClick={runReconciliation} 
            disabled={loading || (datasetMode === 'upload' && !validationResult)}
            style={{ marginTop: '0.5rem' }}
          >
            {loading ? 'Reconciling Data...' : 'Run Reconciliation'}
          </button>
          {data && (
            <button className="btn-secondary" onClick={downloadCSV}>
              Download Report
            </button>
          )}
          {data && (
             <button className="btn-secondary" onClick={clearDataset}>
               Clear Results
             </button>
          )}
        </div>
      </aside>
      
      <main className="main-content">
        <div className="container">
          {/* <header className="header">
        <h1 className="title">Finance Reconciliation Dashboard</h1>
        <div style={{ display: 'flex', gap: '1rem', alignItems: 'center' }}>
          <select value={currentUserRole} onChange={e => setCurrentUserRole(e.target.value)} style={{padding: '0.5rem', borderRadius: '4px'}}>
            <option value="ADMIN">Role: Admin</option>
            <option value="REVIEWER">Role: Reviewer</option>
            <option value="VIEWER">Role: Viewer</option>
          </select>
          {data && (
            <button className="btn-secondary" onClick={downloadCSV}>
              Download Report
            </button>
          )}
          {data && (
             <button className="btn-secondary" onClick={clearDataset}>
               Clear Results
             </button>
          )}
          <button 
            className="btn-primary" 
            onClick={runReconciliation} 
            disabled={loading || (datasetMode === 'upload' && !validationResult)}
          >
            {loading ? 'Reconciling Data...' : 'Run Reconciliation'}
          </button>
        </div>
      </header> */}

            {datasetMode === 'upload' && !data && (
        <>
          <div className="upload-container" style={{ display: 'flex', gap: '1rem', marginBottom: '1rem', flexWrap: 'wrap' }}>
            {['bank', 'settle', 'ledger'].map(source => {
              const labels = { bank: 'Bank Statement', settle: 'Settlement Report', ledger: 'Internal Ledger' };
              return (
                <div key={source} className="upload-card" style={{ flex: 1, minWidth: '250px', padding: '1.5rem', backgroundColor: 'white', borderRadius: '8px', border: '1px solid #e2e8f0', boxShadow: '0 1px 3px rgba(0,0,0,0.1)' }}>
                  <h4 style={{ margin: '0 0 1rem 0' }}>{labels[source]}</h4>
                  <p style={{ fontSize: '0.8rem', color: '#64748b', marginBottom: '1rem' }}>CSV or JSON</p>
                  <input 
                    type="file" 
                    accept=".csv,.json"
                    onChange={e => handleFileChange(source, e.target.files[0])} 
                    style={{ width: '100%' }}
                  />
                  <div style={{ marginTop: '1rem', fontSize: '0.9rem', color: files[source] ? '#10b981' : '#64748b' }}>
                    {files[source] ? `✓ Loaded (${files[source].name})` : 'Status: Not uploaded'}
                  </div>
                </div>
              );
            })}
          </div>
          
          <div style={{ textAlign: 'center', marginBottom: '2rem' }}>
            <button className="btn-primary" onClick={validateData} disabled={isValidationLoading}>
              {isValidationLoading ? 'Validating...' : 'Validate Data'}
            </button>
          </div>
          
          {validationResult && (
            <div className="validation-results" style={{ marginBottom: '2rem', padding: '1.5rem', backgroundColor: 'white', borderRadius: '8px', border: '1px solid #e2e8f0' }}>
              <h3 style={{ marginTop: 0 }}>Data Validation Results</h3>
              <div style={{ display: 'flex', gap: '2rem', flexWrap: 'wrap', marginBottom: '1.5rem' }}>
                {Object.keys(validationResult.sources).map(src => {
                  const srcData = validationResult.sources[src];
                  return (
                    <div key={src} style={{ flex: 1, minWidth: '200px' }}>
                      <h4 style={{ textTransform: 'capitalize' }}>{src.replace('_', ' ')}</h4>
                      <p style={{ margin: '0.2rem 0', color: srcData.records > 0 ? '#10b981' : '#ef4444' }}>{srcData.records > 0 ? `✓ Loaded — ${srcData.records} records` : '✗ Not loaded'}</p>
                      {srcData.records > 0 && (
                        <ul style={{ listStyle: 'none', padding: 0, fontSize: '0.9rem' }}>
                          <li><span style={{color: '#10b981'}}>✓</span> Valid: {srcData.valid_records}</li>
                          <li><span style={{color: srcData.invalid_records > 0 ? '#ef4444' : '#64748b'}}>⚠</span> Invalid: {srcData.invalid_records}</li>
                          <li><span style={{color: srcData.duplicates > 0 ? '#f59e0b' : '#64748b'}}>↻</span> Duplicates: {srcData.duplicates}</li>
                        </ul>
                      )}
                    </div>
                  );
                })}
              </div>
              
              {validationResult.errors && validationResult.errors.length > 0 && (
                <div style={{ marginBottom: '1.5rem' }}>
                  <h4 style={{ color: '#ef4444' }}>Data Quality Errors</h4>
                  <div style={{ maxHeight: '200px', overflowY: 'auto', border: '1px solid #e2e8f0', borderRadius: '4px' }}>
                    <table style={{ width: '100%', fontSize: '0.85rem' }}>
                      <thead style={{ position: 'sticky', top: 0, background: '#f8fafc' }}>
                        <tr>
                          <th style={{ padding: '0.5rem' }}>Source</th>
                          <th style={{ padding: '0.5rem' }}>Row</th>
                          <th style={{ padding: '0.5rem' }}>Field</th>
                          <th style={{ padding: '0.5rem' }}>Value</th>
                          <th style={{ padding: '0.5rem' }}>Error</th>
                        </tr>
                      </thead>
                      <tbody>
                        {validationResult.errors.map((err, i) => (
                          <tr key={i} style={{ borderTop: '1px solid #e2e8f0' }}>
                            <td style={{ padding: '0.5rem', textTransform: 'capitalize' }}>{err.source}</td>
                            <td style={{ padding: '0.5rem' }}>{err.row}</td>
                            <td style={{ padding: '0.5rem' }}>{err.field}</td>
                            <td style={{ padding: '0.5rem' }}>"{err.value}"</td>
                            <td style={{ padding: '0.5rem', color: '#ef4444' }}>{err.error}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <div style={{ marginTop: '1rem' }}>
                    <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer' }}>
                      <input type="checkbox" checked={excludeInvalid} onChange={e => setExcludeInvalid(e.target.checked)} />
                      <span>Exclude invalid rows and continue</span>
                    </label>
                  </div>
                </div>
              )}
              
              {!validationResult.valid && !excludeInvalid ? (
                <div style={{ color: '#ef4444', fontWeight: 'bold' }}>Please fix the errors and re-upload, or choose to exclude invalid rows.</div>
              ) : (
                <div style={{ textAlign: 'center', marginTop: '2rem' }}>
                   <button className="btn-primary" onClick={runReconciliation} disabled={loading}>
                     Start Reconciliation
                   </button>
                </div>
              )}
              
              {/* Data Preview */}
              <div style={{ marginTop: '2rem' }}>
                <h4>Data Previews (First 5 records)</h4>
                {Object.keys(validationResult.sources).map(src => {
                  const srcData = validationResult.sources[src];
                  if (!srcData.preview || srcData.preview.length === 0) return null;
                  const columns = Object.keys(srcData.preview[0]).filter(k => k !== 'raw'); // hide raw
                  return (
                    <div key={`preview-${src}`} style={{ marginBottom: '1rem' }}>
                      <h5 style={{ textTransform: 'capitalize', margin: '0.5rem 0' }}>{src.replace('_', ' ')}</h5>
                      <div style={{ overflowX: 'auto', border: '1px solid #e2e8f0', borderRadius: '4px' }}>
                        <table style={{ width: '100%', fontSize: '0.8rem', whiteSpace: 'nowrap' }}>
                          <thead style={{ background: '#f8fafc' }}>
                            <tr>{columns.map(c => <th key={c} style={{ padding: '0.25rem 0.5rem' }}>{c}</th>)}</tr>
                          </thead>
                          <tbody>
                            {srcData.preview.map((row, i) => (
                              <tr key={i} style={{ borderTop: '1px solid #e2e8f0' }}>
                                {columns.map(c => <td key={c} style={{ padding: '0.25rem 0.5rem' }}>{String(row[c])}</td>)}
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          <div className="template-downloads" style={{ textAlign: 'center', marginBottom: '2rem' }}>
            <p style={{ fontSize: '0.85rem', color: '#64748b', marginBottom: '0.5rem' }}>Need sample data to test?</p>
            <div style={{ display: 'flex', justifyContent: 'center', gap: '1rem' }}>
              <a href="/templates/bank_template.csv" download className="btn-secondary" style={{ fontSize: '0.8rem', padding: '0.25rem 0.75rem', textDecoration: 'none' }}>⬇ Bank Template</a>
              <a href="/templates/settlement_template.csv" download className="btn-secondary" style={{ fontSize: '0.8rem', padding: '0.25rem 0.75rem', textDecoration: 'none' }}>⬇ Settlement Template</a>
              <a href="/templates/ledger_template.csv" download className="btn-secondary" style={{ fontSize: '0.8rem', padding: '0.25rem 0.75rem', textDecoration: 'none' }}>⬇ Ledger Template</a>
            </div>
          </div>
        </>
      )}

      {dataQuality && (
        <div className="data-quality-container" style={{ marginBottom: '2rem', backgroundColor: 'white', borderRadius: '8px', border: '1px solid #e2e8f0', padding: '1.5rem', boxShadow: '0 1px 3px rgba(0,0,0,0.1)' }}>
          <h3 style={{ margin: '0 0 1rem 0', color: '#1e293b' }}>Data Quality Summary</h3>
          <div style={{ display: 'flex', gap: '2rem', flexWrap: 'wrap' }}>
            {['bank', 'settle', 'ledger'].map(src => {
               if (!dataQuality[src]) return null;
               const dq = dataQuality[src];
               return (
                 <div key={src} style={{ flex: 1, minWidth: '200px' }}>
                   <h4 style={{ textTransform: 'capitalize', margin: '0 0 0.5rem 0' }}>{src.replace('_', ' ')}</h4>
                   <ul style={{ listStyle: 'none', padding: 0, margin: 0, fontSize: '0.9rem', color: '#475569' }}>
                     <li><span style={{color: '#10b981'}}>✓</span> Valid Records: {dq.valid_records}</li>
                     <li><span style={{color: dq.invalid_records > 0 ? '#ef4444' : '#64748b'}}>⚠</span> Invalid Records: {dq.invalid_records}</li>
                     <li><span style={{color: dq.duplicates > 0 ? '#f59e0b' : '#64748b'}}>↻</span> Duplicates: {dq.duplicates}</li>
                   </ul>
                   {dq.errors && dq.errors.length > 0 && (
                     <div style={{ marginTop: '0.5rem', fontSize: '0.8rem', color: '#ef4444', maxHeight: '60px', overflowY: 'auto' }}>
                       {dq.errors.map((e,i) => <div key={i}>{e}</div>)}
                     </div>
                   )}
                 </div>
               );
            })}
          </div>
        </div>
      )}

      {error && (
        <div className="error-banner">
          <strong>Error:</strong> {error}
        </div>
      )}

      {!data && !loading && !error && (
        <div className="empty-state">
          <h2>No Data Found</h2>
          <p>Click "Run Reconciliation" to fetch data from the AI Engine.</p>
        </div>
      )}

      {loading && (
        <div className="empty-state">
          <h2>Processing...</h2>
          <p>AI is matching financial records. This may take a few seconds.<br/><strong>{progressState}</strong></p>
        </div>
      )}

      {data && !loading && (
        <>
          {/* Top Row: Cash Position & Sparkline */}
          {forecastData && forecastData.data && (
            <div className="top-dashboard">
              <div className="cash-position">
                <h2>Current Cash Position</h2>
                <div className="cash-value mono">₹{forecastData.data.current_cash_position.toLocaleString('en-IN', {minimumFractionDigits: 2})}</div>
              </div>
              <div className="sparkline-container">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={forecastData.data.forecast_days}>
                    <Line type="monotone" dataKey="closing_balance" stroke="#6366F1" strokeWidth={3} dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </div>
          )}

          {/* Top-Level KPIs */}
          <div className="status-cards">
               {(() => {
                 const allExceptions = [...(data.fuzzy_matched||[]), ...(data.needs_review||[]), ...(data.unmatched||[])];
                 const totalGroups = data.summary?.total_groups || 0;
                 const matchedGroups = data.summary?.fully_matched || 0;
                 const matchRate = data.summary?.match_rate_percent !== undefined ? data.summary.match_rate_percent : (totalGroups > 0 ? ((matchedGroups / totalGroups) * 100).toFixed(1) : 0);
                 const pending = allExceptions.filter(x => ['NEEDS_REVIEW', 'UNRESOLVED', 'PENDING'].includes(x.investigation_state?.resolution)).length;
                 const aiResolved = allExceptions.filter(x => x.investigation_state?.resolution === 'AI_RESOLVED').length;
                 const humanConfirmed = allExceptions.filter(x => x.investigation_state?.resolution === 'HUMAN_CONFIRMED' || x.investigation_state?.resolution === 'MANUAL_MATCH').length;
                 const overrides = allExceptions.filter(x => ['OVERRIDDEN', 'VALID_DIFFERENCE', 'ESCALATED', 'REJECTED'].includes(x.investigation_state?.resolution)).length;
                 
                 const autoResolutionRate = totalGroups > 0 ? (((matchedGroups + aiResolved) / totalGroups) * 100).toFixed(1) : 0;
                 const exceptionRate = totalGroups > 0 ? ((allExceptions.length / totalGroups) * 100).toFixed(1) : 0;
                 
                 // Fix division by zero on AI rate if no human reviews yet
                 const aiReviewedTotal = humanConfirmed + overrides;
                 const aiApprovalRate = aiReviewedTotal > 0 ? Math.round((humanConfirmed / aiReviewedTotal) * 100) : 'N/A';
                 const humanOverrideRate = overrides > 0 ? Math.round((overrides / aiReviewedTotal) * 100) : 0;
                 
                 return (
                   <>
                    {/* RECONCILIATION KPIs */}

                    <div className="status-card fully-matched">
                      <h3 className="status-card-title">Fully Matched</h3>
                      <p className="status-card-value mono">{matchedGroups}</p>
                    </div>
                    <div className="status-card fuzzy-matched">
                      <h3 className="status-card-title">Fuzzy Matched</h3>
                      <p className="status-card-value mono">{data.summary?.fuzzy_matched || 0}</p>
                    </div>
                    <div className="status-card needs-review">
                      <h3 className="status-card-title">Needs Review</h3>
                      <p className="status-card-value mono">{data.summary?.needs_review || 0}</p>
                    </div>
                    <div className="status-card unmatched">
                      <h3 className="status-card-title">Unmatched</h3>
                      <p className="status-card-value mono">{data.summary?.unmatched || 0}</p>
                    </div>
                    
                    <div className="card" style={{gridColumn: '1 / -1', background: 'transparent', border: 'none', boxShadow: 'none', padding: '0 0 1rem 0', marginTop: '1rem', borderTop: '1px solid #e2e8f0'}}>
                        <h2 style={{margin: 0, color: '#0f172a'}}>Reconciliation Operations</h2>
                    </div>
                    <div className="card" title="Total Groups Processed">
                      <h3 className="card-title">Records Processed</h3>
                      <p className="card-value value-neutral mono">{totalGroups}</p>
                    </div>
                    <div className="card" title="Matched groups / Total groups">
                      <h3 className="card-title">Match Rate</h3>
                      <p className="card-value value-success mono">{matchRate}%</p>
                    </div>
                    <div className="card" title="Cases awaiting human review">
                      <h3 className="card-title">Unresolved Cases</h3>
                      <p className="card-value value-danger mono">{pending}</p>
                    </div>

                    {/* AI PERFORMANCE KPIs */}
                    <div className="card" style={{gridColumn: '1 / -1', background: 'transparent', border: 'none', boxShadow: 'none', padding: '1rem 0', marginTop: '1rem', borderTop: '1px solid #e2e8f0'}}>
                        <h2 style={{margin: 0, color: '#0f172a'}}>AI Copilot Performance</h2>
                    </div>
                    <div className="card" title="Cases investigated by AI">
                      <h3 className="card-title">AI Investigated</h3>
                      <p className="card-value value-neutral">{allExceptions.length}</p>
                    </div>
                    <div className="card" title="Cases autonomously resolved by AI">
                      <h3 className="card-title">AI Resolved</h3>
                      <p className="card-value value-primary">{aiResolved}</p>
                    </div>
                    <div className="card" title="AI resolutions approved by humans / AI resolutions reviewed">
                      <h3 className="card-title">AI Approval Rate</h3>
                      <p className="card-value value-success">{aiApprovalRate}{aiApprovalRate !== 'N/A' ? '%' : ''}</p>
                    </div>
                    <div className="card" title="AI resolutions overridden by humans / AI resolutions reviewed">
                      <h3 className="card-title">Human Override Rate</h3>
                      <p className="card-value value-warning">{humanOverrideRate}%</p>
                    </div>

                    {/* TOP RISKS */}
                    <div className="card" style={{gridColumn: '1 / -1', background: '#fee2e2', border: '1px solid #ef4444'}}>
                        <h3 className="card-title" style={{color: '#b91c1c'}}>Top Finance Risks</h3>
                        <ul style={{ margin: '0.5rem 0 0 0', paddingLeft: '1.5rem', color: '#7f1d1d' }}>
                           {allExceptions.filter(e => e.investigation_state?.priority === 'CRITICAL').length > 0 && (
                               <li><strong>{allExceptions.filter(e => e.investigation_state?.priority === 'CRITICAL').length}</strong> High Priority Exceptions unresolved.</li>
                           )}
                           {forecastData && forecastData.data?.risk_alerts?.length > 0 ? (
                               forecastData.data.risk_alerts.map((alert, i) => (
                                   <li key={i}>Cash falls below safe threshold on <strong>{alert.date}</strong> (Shortfall: ₹{alert.shortfall.toLocaleString('en-IN')})</li>
                               ))
                           ) : (
                               <li>No immediate cash risks detected.</li>
                           )}
                        </ul>
                    </div>
                   </>
                 )
               })()}
          </div>

          <div className="chart-container">
            <h3 style={{ marginTop: 0, marginBottom: '1.5rem', color: '#1e293b' }}>Match Distribution Overview</h3>
            <div style={{ height: '300px' }}>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={getChartData()}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
                  <XAxis dataKey="name" axisLine={false} tickLine={false} />
                  <YAxis axisLine={false} tickLine={false} />
                  <Tooltip cursor={{ fill: '#f1f5f9' }} />
                  <Bar dataKey="value" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Model Evaluation & Accuracy Panel */}
          {/* Model Evaluation & Accuracy Panel */}
          <div className="evaluation-panel" style={{ padding: '1.5rem', background: '#fff', borderRadius: '8px', border: '1px solid #e2e8f0', marginBottom: '2rem', boxShadow: '0 4px 6px -1px rgba(0, 0, 0, 0.1)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.5rem' }}>
                <h3 style={{ margin: 0, color: '#1e293b', fontSize: '1.5rem' }}>Model & Reconciliation Performance</h3>
                {evalData && (
                    <div style={{ fontSize: '0.9rem', color: '#64748b' }}>
                        Processing Throughput: <strong>{evalData.performance?.throughput_per_sec} groups/sec</strong>
                    </div>
                )}
            </div>
            
            {evalError ? (
              <div className="eval-error-message" style={{ color: '#ef4444', background: '#fee2e2', padding: '1rem', borderRadius: '4px' }}>
                <p style={{ margin: 0 }}>{evalError}</p>
              </div>
            ) : evalData ? (
              <div className="eval-content">
                
                {/* Top Metrics */}
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '1rem', marginBottom: '2rem' }}>
                  <div style={{ padding: '1rem', background: '#f8fafc', borderRadius: '8px', border: '1px solid #e2e8f0', textAlign: 'center' }}>
                    <h4 style={{ margin: '0 0 0.5rem 0', color: '#64748b', fontSize: '0.9rem' }}>Accuracy</h4>
                    <div style={{ fontSize: '1.8rem', fontWeight: 'bold', color: evalData.overall_accuracy >= 90 ? '#10b981' : '#f59e0b' }}>
                      {evalData.overall_accuracy}%
                    </div>
                  </div>
                  <div style={{ padding: '1rem', background: '#f8fafc', borderRadius: '8px', border: '1px solid #e2e8f0', textAlign: 'center' }}>
                    <h4 style={{ margin: '0 0 0.5rem 0', color: '#64748b', fontSize: '0.9rem', title: 'Average Precision across all classes' }}>Macro Precision</h4>
                    <div style={{ fontSize: '1.8rem', fontWeight: 'bold', color: '#334155' }}>
                      {evalData.macro_precision}{evalData.macro_precision !== 'N/A' ? '%' : ''}
                    </div>
                  </div>
                  <div style={{ padding: '1rem', background: '#f8fafc', borderRadius: '8px', border: '1px solid #e2e8f0', textAlign: 'center' }}>
                    <h4 style={{ margin: '0 0 0.5rem 0', color: '#64748b', fontSize: '0.9rem', title: 'Average Recall across all classes' }}>Macro Recall</h4>
                    <div style={{ fontSize: '1.8rem', fontWeight: 'bold', color: '#334155' }}>
                      {evalData.macro_recall}{evalData.macro_recall !== 'N/A' ? '%' : ''}
                    </div>
                  </div>
                  <div style={{ padding: '1rem', background: '#f8fafc', borderRadius: '8px', border: '1px solid #e2e8f0', textAlign: 'center' }}>
                    <h4 style={{ margin: '0 0 0.5rem 0', color: '#64748b', fontSize: '0.9rem', title: 'Harmonic mean of Precision and Recall' }}>F1 Score</h4>
                    <div style={{ fontSize: '1.8rem', fontWeight: 'bold', color: '#3b82f6' }}>
                      {evalData.macro_f1}
                    </div>
                  </div>
                  <div style={{ padding: '1rem', background: evalData.high_confidence_error_rate > 0 ? '#fee2e2' : '#dcfce3', borderRadius: '8px', border: '1px solid #e2e8f0', textAlign: 'center' }}>
                    <h4 style={{ margin: '0 0 0.5rem 0', color: evalData.high_confidence_error_rate > 0 ? '#b91c1c' : '#166534', fontSize: '0.9rem', title: 'Errors made with >90% confidence' }}>High-Confidence Errors</h4>
                    <div style={{ fontSize: '1.8rem', fontWeight: 'bold', color: evalData.high_confidence_error_rate > 0 ? '#ef4444' : '#10b981' }}>
                      {evalData.high_confidence_error_rate}{evalData.high_confidence_error_rate !== 'N/A' ? '%' : ''}
                    </div>
                  </div>
                </div>

                {/* Confusion Matrix */}
                <h4 style={{ margin: '0 0 1rem 0', color: '#1e293b' }}>Confusion Matrix (Expected vs Predicted)</h4>
                <div style={{ overflowX: 'auto', marginBottom: '2rem' }}>
                  <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'center', fontSize: '0.9rem' }}>
                    <thead>
                      <tr>
                        <th style={{ padding: '0.75rem', border: '1px solid #cbd5e1', background: '#f1f5f9' }}>Expected \ Predicted</th>
                        {Object.keys(evalData.confusion_matrix || {}).map(cat => (
                           <th key={cat} style={{ padding: '0.75rem', border: '1px solid #cbd5e1', background: '#f8fafc', fontWeight: '600', fontSize: '0.8rem' }}>{cat.replace('_', ' ')}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {Object.keys(evalData.confusion_matrix || {}).map(expected => (
                        <tr key={expected}>
                          <td style={{ padding: '0.75rem', border: '1px solid #cbd5e1', background: '#f8fafc', fontWeight: '600', textAlign: 'left', fontSize: '0.8rem' }}>{expected.replace('_', ' ')}</td>
                          {Object.keys(evalData.confusion_matrix[expected] || {}).map(predicted => {
                              const count = evalData.confusion_matrix[expected][predicted];
                              const isCorrect = expected === predicted;
                              return (
                                <td key={predicted} style={{ 
                                    padding: '0.75rem', 
                                    border: '1px solid #cbd5e1',
                                    background: count > 0 ? (isCorrect ? '#dcfce3' : '#fee2e2') : '#ffffff',
                                    color: count > 0 ? (isCorrect ? '#166534' : '#b91c1c') : '#cbd5e1',
                                    fontWeight: count > 0 ? 'bold' : 'normal'
                                }}>
                                  {count}
                                </td>
                              );
                          })}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                {/* Error Breakdown */}
                {evalData.misclassified_examples && evalData.misclassified_examples.length > 0 && (
                  <details className="eval-misclassified" style={{ background: '#f8fafc', padding: '1rem', borderRadius: '8px', border: '1px solid #e2e8f0' }}>
                    <summary style={{ cursor: 'pointer', fontWeight: 'bold', color: '#334155' }}>View Error Analysis ({evalData.misclassified_examples.length} Errors)</summary>
                    <div className="misclassified-list" style={{ marginTop: '1rem', display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                      {evalData.misclassified_examples.map((ex, idx) => (
                        <div key={idx} className="misclassified-item" style={{ padding: '0.75rem', background: '#fff', borderLeft: '4px solid #ef4444', borderRadius: '4px', boxShadow: '0 1px 2px rgba(0,0,0,0.05)', display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr', gap: '0.5rem', fontSize: '0.85rem' }}>
                          <span className="group-id"><strong>Group:</strong> {ex.group_id}</span>
                          <span className="expected" style={{ color: '#166534' }}><strong>Expected:</strong> {ex.expected} <br/><small>({ex.expected_exception})</small></span>
                          <span className="pred" style={{ color: '#b91c1c' }}><strong>Predicted:</strong> {ex.predicted}</span>
                          <span className="conf"><strong>Confidence:</strong> {ex.confidence}% <br/><small>({ex.resolution})</small></span>
                        </div>
                      ))}
                    </div>
                  </details>
                )}
              </div>
            ) : (
              <div className="eval-loading" style={{ padding: '2rem', textAlign: 'center', color: '#64748b' }}>
                <p>Evaluating accuracy against Ground Truth...</p>
              </div>
            )}
          </div>

          {/* Real-Time Cash Position & 7-Day Forecast */}
          <div className="forecast-panel" style={{ padding: '1.5rem', background: '#fff', borderRadius: '8px', border: '1px solid #e2e8f0', marginBottom: '2rem', boxShadow: '0 4px 6px -1px rgba(0, 0, 0, 0.1)' }}>
            <h3 style={{ marginTop: 0, marginBottom: '1.5rem', color: '#1e293b', fontSize: '1.5rem' }}>Cash & Forecast</h3>
            {forecastError ? (
              <div className="forecast-error-message">
                <p>{forecastError}</p>
              </div>
            ) : forecastData && forecastData.data ? (
              <div className="forecast-content">
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '1rem', marginBottom: '1.5rem' }}>
                    <div style={{ padding: '1rem', background: '#f8fafc', borderRadius: '8px', border: '1px solid #e2e8f0' }}>
                        <h4 style={{ margin: '0 0 0.5rem 0', color: '#64748b', fontSize: '0.9rem' }}>Current Cash Position</h4>
                        <div style={{ fontSize: '1.5rem', fontWeight: 'bold', color: '#0f172a' }}>₹{forecastData.data.current_cash_position.toLocaleString('en-IN', {minimumFractionDigits: 2})}</div>
                        <div style={{ fontSize: '0.8rem', color: '#64748b', marginTop: '0.25rem' }}>As of: {forecastData.data.as_of_date}</div>
                    </div>
                    <div style={{ padding: '1rem', background: '#f8fafc', borderRadius: '8px', border: '1px solid #e2e8f0' }}>
                        <h4 style={{ margin: '0 0 0.5rem 0', color: '#64748b', fontSize: '0.9rem' }}>Pending Inflows</h4>
                        <div style={{ fontSize: '1.5rem', fontWeight: 'bold', color: '#10b981' }}>+₹{forecastData.data.pending_inflows.toLocaleString('en-IN', {minimumFractionDigits: 2})}</div>
                    </div>
                    <div style={{ padding: '1rem', background: '#f8fafc', borderRadius: '8px', border: '1px solid #e2e8f0' }}>
                        <h4 style={{ margin: '0 0 0.5rem 0', color: '#64748b', fontSize: '0.9rem' }}>Pending Outflows</h4>
                        <div style={{ fontSize: '1.5rem', fontWeight: 'bold', color: '#ef4444' }}>-₹{forecastData.data.pending_outflows.toLocaleString('en-IN', {minimumFractionDigits: 2})}</div>
                    </div>
                    <div style={{ padding: '1rem', background: '#f8fafc', borderRadius: '8px', border: '1px solid #e2e8f0' }}>
                        <h4 style={{ margin: '0 0 0.5rem 0', color: '#64748b', fontSize: '0.9rem' }}>Net Expected Change</h4>
                        <div style={{ fontSize: '1.5rem', fontWeight: 'bold', color: forecastData.data.net_pending_change >= 0 ? '#10b981' : '#ef4444' }}>{forecastData.data.net_pending_change >= 0 ? '+' : ''}₹{forecastData.data.net_pending_change.toLocaleString('en-IN', {minimumFractionDigits: 2})}</div>
                    </div>
                </div>
                
                {forecastData.data.risk_alerts && forecastData.data.risk_alerts.length > 0 && (
                  <div style={{ padding: '1rem', background: '#fee2e2', borderLeft: '4px solid #ef4444', borderRadius: '4px', marginBottom: '1.5rem' }}>
                    <h4 style={{ margin: '0 0 0.5rem 0', color: '#b91c1c' }}>⚠️ Cash Risk Detected</h4>
                    {forecastData.data.risk_alerts.map((alert, idx) => (
                      <div key={idx} style={{ color: '#7f1d1d', fontSize: '0.9rem' }}>
                        On <strong>{alert.date}</strong>, forecast cash (₹{alert.forecast_cash.toLocaleString('en-IN', {minimumFractionDigits: 2})}) falls below minimum safe threshold (₹{alert.threshold.toLocaleString('en-IN')}). Shortfall: ₹{alert.shortfall.toLocaleString('en-IN', {minimumFractionDigits: 2})}.
                      </div>
                    ))}
                  </div>
                )}
                
                <h4 style={{ marginBottom: '1rem', color: '#334155' }}>7-Day Forecast Projection</h4>
                <div style={{ height: '350px', marginBottom: '1.5rem' }}>
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={forecastData.data.forecast_days} margin={{ top: 5, right: 30, left: 20, bottom: 5 }}>
                      <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
                      <XAxis dataKey="date" axisLine={false} tickLine={false} tick={{fill: '#64748b', fontSize: 12}} />
                      <YAxis axisLine={false} tickLine={false} tickFormatter={(val) => `₹${(val/1000)}k`} tick={{fill: '#64748b', fontSize: 12}} />
                      <Tooltip cursor={{ fill: '#f1f5f9' }} formatter={(value) => `₹${value.toLocaleString('en-IN', {minimumFractionDigits: 2})}`} />
                      <Line type="monotone" name="Closing Balance" dataKey="closing_balance" stroke="#2563eb" strokeWidth={3} dot={{ r: 4, strokeWidth: 2 }} activeDot={{ r: 6 }} />
                      <Line type="step" name="Min Threshold" dataKey={() => forecastData.data.minimum_safe_cash} stroke="#ef4444" strokeWidth={2} strokeDasharray="5 5" dot={false} />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
                
                <div style={{ display: 'flex', gap: '2rem', flexWrap: 'wrap', marginBottom: '1.5rem' }}>
                    <div style={{ flex: 1, minWidth: '300px' }}>
                        <h4 style={{ color: '#334155', borderBottom: '1px solid #e2e8f0', paddingBottom: '0.5rem' }}>Top Inflows</h4>
                        <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
                            {forecastData.data.top_drivers.inflows.length === 0 ? <li style={{ color: '#64748b', fontSize: '0.9rem', padding: '0.5rem 0' }}>No pending inflows.</li> : forecastData.data.top_drivers.inflows.map((item, idx) => (
                                <li key={idx} style={{ display: 'flex', justifyContent: 'space-between', padding: '0.5rem 0', borderBottom: '1px solid #f1f5f9' }}>
                                    <span style={{ color: '#475569', fontSize: '0.9rem' }}>{item.description} <br/><small>{item.date}</small></span>
                                    <span style={{ color: '#10b981', fontWeight: 'bold' }}>+₹{item.amount.toLocaleString('en-IN', {minimumFractionDigits: 2})}</span>
                                </li>
                            ))}
                        </ul>
                    </div>
                    <div style={{ flex: 1, minWidth: '300px' }}>
                        <h4 style={{ color: '#334155', borderBottom: '1px solid #e2e8f0', paddingBottom: '0.5rem' }}>Top Outflows</h4>
                        <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
                            {forecastData.data.top_drivers.outflows.length === 0 ? <li style={{ color: '#64748b', fontSize: '0.9rem', padding: '0.5rem 0' }}>No pending outflows.</li> : forecastData.data.top_drivers.outflows.map((item, idx) => (
                                <li key={idx} style={{ display: 'flex', justifyContent: 'space-between', padding: '0.5rem 0', borderBottom: '1px solid #f1f5f9' }}>
                                    <span style={{ color: '#475569', fontSize: '0.9rem' }}>{item.description} <br/><small>{item.date}</small></span>
                                    <span style={{ color: '#ef4444', fontWeight: 'bold' }}>-₹{item.amount.toLocaleString('en-IN', {minimumFractionDigits: 2})}</span>
                                </li>
                            ))}
                        </ul>
                    </div>
                </div>

                <div style={{ padding: '1rem', background: '#f8fafc', borderRadius: '8px', border: '1px solid #e2e8f0' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
                        <h4 style={{ margin: 0, color: '#334155' }}>Forecast Summary</h4>
                        <span className={`badge ${forecastData.data.confidence === 'HIGH' ? 'badge-success' : (forecastData.data.confidence === 'MEDIUM' ? 'badge-warning' : 'badge-danger')}`}>Confidence: {forecastData.data.confidence}</span>
                    </div>
                    <p style={{ color: '#475569', fontSize: '0.95rem', lineHeight: '1.5' }}>{forecastData.data.explanation_summary}</p>
                    {forecastData.data.confidence_issues && forecastData.data.confidence_issues.length > 0 && (
                        <ul style={{ listStyleType: 'disc', paddingLeft: '1.5rem', color: '#f59e0b', fontSize: '0.85rem' }}>
                            {forecastData.data.confidence_issues.map((issue, idx) => <li key={idx}>{issue}</li>)}
                        </ul>
                    )}
                </div>
              </div>
            ) : (
              <div className="forecast-loading">
                <p>Generating cash flow forecast...</p>
              </div>
            )}
          </div>

          <div className="exceptions-container">
            <div className="exceptions-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '1rem' }}>
              <h3 className="exceptions-title">High-Value / Priority Exceptions</h3>
              <div className="filters-row" style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', flexWrap: 'wrap' }}>
                <select value={filterType} onChange={e => setFilterType(e.target.value)} className="filter-input">
                  <option value="All">All Types</option>
                  <option value="Fully Matched">Fully Matched</option>
                  <option value="Fuzzy Matched">Fuzzy Matched</option>
                  <option value="Needs Review">Needs Review</option>
                  <option value="Unmatched">Unmatched</option>
                </select>
                
                <select value={filterSource} onChange={e => setFilterSource(e.target.value)} className="filter-input">
                  <option value="All">All Sources</option>
                  <option value="Multiple">Multiple</option>
                  <option value="Bank Statement">Bank Statement</option>
                  <option value="Settlement">Settlement</option>
                  <option value="Ledger">Ledger</option>
                </select>
                
                <input 
                  type="text" 
                  placeholder="Search amount or date..." 
                  value={searchQuery} 
                  onChange={e => setSearchQuery(e.target.value)} 
                  className="filter-input" 
                />
                
                <button 
                  className="btn-secondary" 
                  style={{ padding: '0.5rem 1rem' }} 
                  onClick={() => { setFilterType('All'); setFilterSource('All'); setSearchQuery(''); }}
                >
                  Clear
                </button>
              </div>
            </div>
            
            {currentUserRole !== 'VIEWER' && selectedExceptions.size > 0 && (
              <div style={{ padding: '1rem', background: '#e0e7ff', border: '1px solid #c7d2fe', borderRadius: '4px', marginBottom: '1rem', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span><strong>{selectedExceptions.size}</strong> cases selected for Bulk Approval</span>
                <button className="btn-primary" onClick={async () => {
                   if (window.confirm(`You are approving ${selectedExceptions.size} exceptions. Only high confidence, deterministic cases will be processed. Proceed?`)) {
                      const exps = Array.from(selectedExceptions).map(id => getFilteredList().find(e => e.id === id)).filter(Boolean);
                      for (const exp of exps) {
                          if (exp.confidence >= 90 && exp.resolution !== 'HUMAN_CONFIRMED' && exp.resolution !== 'OVERRIDDEN') {
                              await handleResolutionAction(exp.raw, 'Accept', 'Bulk Approved');
                          }
                      }
                      setSelectedExceptions(new Set());
                   }
                }}>Bulk Approve Safe Cases</button>
              </div>
            )}
            <div className="table-wrapper">
              <table>
                <thead>
                  <tr>
                    {currentUserRole !== 'VIEWER' && <th>
                      <input type="checkbox" onChange={(e) => {
                          if (e.target.checked) {
                              const safeIds = getFilteredList().filter(x => x.confidence >= 90 && x.resolution !== 'HUMAN_CONFIRMED').map(x => x.id);
                              setSelectedExceptions(new Set(safeIds));
                          } else {
                              setSelectedExceptions(new Set());
                          }
                      }} />
                    </th>}
                    <th>Exception ID</th>
                    <th>Transaction</th>
                    <th onClick={() => handleSort('priority')} style={{cursor: 'pointer'}}>Priority {sortConfig.key === 'priority' ? (sortConfig.direction === 'asc' ? '↑' : '↓') : ''}</th>
                    <th>Type</th>
                    <th onClick={() => handleSort('date')} style={{cursor: 'pointer'}}>Date {sortConfig.key === 'date' ? (sortConfig.direction === 'asc' ? '↑' : '↓') : ''}</th>
                    <th onClick={() => handleSort('amount')} style={{cursor: 'pointer'}}>Amount {sortConfig.key === 'amount' ? (sortConfig.direction === 'asc' ? '↑' : '↓') : ''}</th>
                    <th>Resolution</th>
                    <th onClick={() => handleSort('confidence')} style={{cursor: 'pointer'}}>AI Confidence {sortConfig.key === 'confidence' ? (sortConfig.direction === 'asc' ? '↑' : '↓') : ''}</th>
                  </tr>
                </thead>
                <tbody>
                  {getFilteredList().map((exp, idx) => (
                    <tr key={idx} onClick={() => handleSelectException(exp.raw)} className="clickable-row">
                      {currentUserRole !== 'VIEWER' && <td onClick={(e) => e.stopPropagation()}>
                        <input type="checkbox" checked={selectedExceptions.has(exp.id)} onChange={(e) => {
                            const newSet = new Set(selectedExceptions);
                            if (e.target.checked) newSet.add(exp.id);
                            else newSet.delete(exp.id);
                            setSelectedExceptions(newSet);
                        }} disabled={exp.confidence < 90 || exp.resolution === 'HUMAN_CONFIRMED'} />
                      </td>}
                      <td className="mono" style={{ fontSize: '0.85rem' }}>{exp.id.substring(0, 8)}...</td>
                      <td className="mono" style={{ fontSize: '0.85rem' }}>{exp.raw?.investigation_state?.transaction_id || 'N/A'}</td>
                      <td>
                        <span className={`badge ${exp.priority === 'CRITICAL' ? 'badge-danger' : (exp.priority === 'HIGH' ? 'badge-warning' : (exp.priority === 'MEDIUM' ? 'badge-primary' : ''))}`}>
                          {exp.priority}
                        </span>
                      </td>
                      <td>
                        <span className={`badge ${exp.type === 'Fully Matched' ? 'badge-success' : (exp.type === 'Fuzzy Matched' ? 'badge-warning' : (exp.type === 'Unmatched' ? 'badge-danger' : 'badge-primary'))}`} style={(exp.type !== 'Fully Matched' && exp.type !== 'Fuzzy Matched' && exp.type !== 'Unmatched') ? {backgroundColor: '#f97316', color: 'white'} : (exp.type === 'Fully Matched' ? {backgroundColor: '#10b981', color: 'white'} : {})}>
                          {exp.type}
                        </span>
                      </td>
                      <td className="mono">{exp.date}</td>
                      <td className="mono">₹{exp.amount?.toLocaleString('en-IN', {minimumFractionDigits: 2})}</td>
                      <td><span className={`badge ${['AI_RESOLVED', 'AUTO_RESOLVED', 'HUMAN_CONFIRMED'].includes(exp.resolution) ? 'badge-success' : (['REJECTED'].includes(exp.resolution) ? 'badge-danger' : 'badge-warning')}`}>{exp.resolution}</span></td>
                      <td>
                        {exp.confidence !== undefined && (
                          <span style={{ fontSize: '0.75rem', color: '#64748b', marginRight: '8px' }}>
                            {Math.round(exp.confidence)}%
                          </span>
                        )}
                        <span style={{ fontSize: '0.75rem', color: '#3b82f6', cursor: 'pointer', textDecoration: 'underline' }}>
                          Details
                        </span>
                      </td>
                    </tr>
                  ))}
                  {getFilteredList().length === 0 && (
                    <tr>
                      <td colSpan="8" style={{ textAlign: 'center', color: '#64748b', padding: '3rem' }}>
                        No matching records found
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>

            </div>
          </div>

          {selectedException && (
            <div className="side-panel-backdrop" onClick={closeModal}>
              <div className="side-panel" onClick={(e) => e.stopPropagation()}>
                <div className="side-panel-header">
                  <h2>Exception Details</h2>
                  <button className="panel-close" onClick={closeModal}>&times;</button>
                </div>
                <div className="side-panel-content">
                
                {/* ---------------- EXCEPTION ---------------- */}
                <div style={{marginBottom: '1.5rem', padding: '1rem', background: '#f8fafc', borderRadius: '8px'}}>
                  <h3 style={{marginTop: 0}}>Exception Overview</h3>
                  <div style={{display: 'flex', gap: '2rem', flexWrap: 'wrap'}}>
                    <div><strong>Transaction:</strong> {selectedException.investigation_state?.transaction_id || selectedException.group_id}</div>
                    <div><strong>Type:</strong> <span className="badge" style={{backgroundColor: '#f97316', color: 'white'}}>{selectedException.investigation_state?.exception_type || selectedException.status}</span></div>
                    <div><strong>Status:</strong> <span className="badge" style={{backgroundColor: '#3b82f6', color: 'white'}}>{selectedException.investigation_state?.resolution || 'PENDING'}</span></div>
                    {selectedException.investigation_state?.priority && (
                      <div><strong>Priority:</strong> <span className={`badge ${selectedException.investigation_state.priority === 'CRITICAL' ? 'badge-danger' : (selectedException.investigation_state.priority === 'HIGH' ? 'badge-warning' : 'badge-primary')}`}>{selectedException.investigation_state.priority}</span></div>
                    )}
                    {selectedException.investigation_state?.confidence !== undefined && (
                        <div><strong>Confidence:</strong> {Math.round(selectedException.investigation_state.confidence * 100)}%</div>
                    )}
                  </div>
                </div>

                {/* ---------------- SOURCE COMPARISON ---------------- */}
                <h3 style={{ borderBottom: '1px solid #e2e8f0', paddingBottom: '0.5rem' }}>Source Comparison</h3>
                <div className="modal-grid" style={{marginBottom: '1.5rem'}}>
                  {['bank', 'settlement', 'ledger'].map(src => {
                     const srcData = selectedException.investigation_state?.source_records?.[src];
                     return (
                      <div className="modal-column" key={src}>
                        <h4 style={{textTransform: 'capitalize'}}>{src}</h4>
                        {srcData ? (
                            <div className="record-details">
                              <p><strong>Date:</strong> {srcData.date || 'N/A'}</p>
                              <p><strong>Amount:</strong> {srcData.amount !== null ? `₹${srcData.amount}` : 'N/A'}</p>
                              <p><strong>ID/UTR:</strong> {srcData.utr || srcData.id || 'N/A'}</p>
                            </div>
                        ) : (
                            <div className="record-details" style={{color: '#ef4444'}}>Not found</div>
                        )}
                      </div>
                     );
                  })}
                </div>

                {/* ---------------- INVESTIGATION ---------------- */}
                {selectedException.investigation_state?.investigation_steps && (
                    <div className="ai-generated-content">
                      <h3>AI Investigation Steps</h3>
                      <ul style={{listStyleType: 'none', paddingLeft: 0}}>
                        {selectedException.investigation_state.investigation_steps.map((step, idx) => (
                           <li key={idx} style={{marginBottom: '0.5rem'}}><span style={{color: '#10b981', marginRight: '0.5rem'}}>✓</span>{step}</li>
                        ))}
                      </ul>
                    </div>
                )}

                {/* ---------------- EVIDENCE ---------------- */}
                {selectedException.investigation_state?.evidence && selectedException.investigation_state.evidence.length > 0 && (
                    <div style={{marginBottom: '1.5rem'}}>
                      <h3 style={{ borderBottom: '1px solid #e2e8f0', paddingBottom: '0.5rem' }}>Evidence Collected</h3>
                      {selectedException.investigation_state.evidence.map((ev, i) => (
                         <div key={i} style={{padding: '0.5rem', background: '#f1f5f9', marginBottom: '0.5rem', borderRadius: '4px'}}>
                            <strong>{ev.tool}:</strong> {JSON.stringify(ev.result)}
                         </div>
                      ))}
                    </div>
                )}

                {/* ---------------- AI CONCLUSION ---------------- */}
                {selectedException.investigation_state?.root_cause && (
                    <div className="ai-generated-content">
                      <h3>AI Conclusion</h3>
                      <p>{selectedException.investigation_state.root_cause}</p>
                    </div>
                )}

                {/* ---------------- RECOMMENDATION ---------------- */}
                {selectedException.investigation_state?.recommendation && (
                    <div className="ai-generated-content">
                      <h3>AI Recommendation</h3>
                      <p>{selectedException.investigation_state.recommendation}</p>
                    </div>
                )}

                {/* ---------------- MANUAL MATCH ---------------- */}
                {selectedException.investigation_state?.candidate_records && selectedException.investigation_state.candidate_records.length > 0 && (
                    <div style={{marginBottom: '1.5rem', padding: '1rem', background: '#f8fafc', borderLeft: '4px solid #8b5cf6'}}>
                      <h3 style={{marginTop: 0}}>Candidate Records</h3>
                      <ul style={{listStyleType: 'none', paddingLeft: 0}}>
                        {selectedException.investigation_state.candidate_records.map((c, idx) => (
                           <li key={idx} style={{marginBottom: '0.5rem', display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '0.5rem', background: 'white', border: '1px solid #e2e8f0'}}>
                              <span><strong>{c.source.toUpperCase()}:</strong> {c.normalized_record?.id || c.normalized_record?.utr} - ₹{c.normalized_record?.amount} - {c.normalized_record?.date}</span>
                              {currentUserRole !== 'VIEWER' && (
                                <button className="btn-secondary" style={{padding: '0.2rem 0.5rem', fontSize: '0.8rem'}} onClick={() => {
                                    if(window.confirm('Confirm manual match?')) handleResolutionAction(selectedException, 'Manual Match', 'Matched to ' + (c.normalized_record?.id || c.normalized_record?.utr));
                                }}>Select Match</button>
                              )}
                           </li>
                        ))}
                      </ul>
                    </div>
                )}
                
                
                {/* ---------------- AUDIT TIMELINE ---------------- */}
                <h3 style={{ borderBottom: '1px solid #e2e8f0', paddingBottom: '0.5rem', marginTop: '2rem' }}>Audit Timeline</h3>
                <div style={{ marginBottom: '1.5rem', padding: '1rem', background: '#f8fafc', borderRadius: '8px' }}>
                    {auditTimeline.length === 0 ? <p>No audit events recorded yet.</p> : (
                        <ul style={{ listStyleType: 'none', paddingLeft: '1rem', borderLeft: '2px solid #cbd5e1' }}>
                            {auditTimeline.map((event, idx) => (
                                <li key={event.event_id} style={{ position: 'relative', paddingBottom: '1.5rem' }}>
                                    <div style={{ position: 'absolute', left: '-1.35rem', top: '0', width: '12px', height: '12px', borderRadius: '50%', background: event.actor_type === 'SYSTEM' ? '#94a3b8' : (event.actor_type === 'AI' ? '#8b5cf6' : '#3b82f6') }}></div>
                                    <div style={{ fontWeight: 'bold' }}>{event.event_type.replace(/_/g, ' ')} <span style={{fontSize: '0.8rem', color: '#64748b', fontWeight: 'normal', marginLeft: '0.5rem'}}>{new Date(event.timestamp).toLocaleString()}</span></div>
                                    <div style={{ fontSize: '0.9rem', marginTop: '0.25rem' }}>
                                        <strong>Actor:</strong> <span className={`badge`} style={{backgroundColor: event.actor_type === 'SYSTEM' ? '#94a3b8' : (event.actor_type === 'AI' ? '#8b5cf6' : '#3b82f6'), color: 'white', fontSize: '0.7rem', padding: '0.1rem 0.3rem'}}>{event.actor_type}</span> {event.actor_role && `(${event.actor_role})`}
                                    </div>
                                    {event.decision && (
                                        <div style={{ fontSize: '0.9rem', marginTop: '0.25rem' }}><strong>Decision:</strong> {event.decision}</div>
                                    )}
                                    {event.reason && (
                                        <div style={{ fontSize: '0.9rem', marginTop: '0.25rem', fontStyle: 'italic' }}>"{event.reason}"</div>
                                    )}
                                    {event.previous_status && event.new_status && event.previous_status !== event.new_status && (
                                        <div style={{ fontSize: '0.9rem', marginTop: '0.5rem', padding: '0.5rem', background: '#eef2ff', borderRadius: '4px' }}>
                                            <strong>Status Change:</strong> <span style={{textDecoration: 'line-through', color: '#ef4444'}}>{event.previous_status}</span> &rarr; <span style={{color: '#10b981', fontWeight: 'bold'}}>{event.new_status}</span>
                                        </div>
                                    )}
                                </li>
                            ))}
                        </ul>
                    )}
                </div>

                {/* ---------------- NOTES ---------------- */}
                {selectedException.investigation_state?.notes && selectedException.investigation_state.notes.length > 0 && (
                    <div style={{marginBottom: '1.5rem', padding: '1rem', background: '#f8fafc', borderLeft: '4px solid #94a3b8'}}>
                      <h3 style={{marginTop: 0}}>Reviewer Notes</h3>
                      <ul style={{listStyleType: 'none', paddingLeft: 0}}>
                        {selectedException.investigation_state.notes.map((n, idx) => (
                           <li key={idx} style={{marginBottom: '0.5rem', fontSize: '0.9rem'}}>
                              <strong>{n.author}</strong> <span style={{color: '#64748b', fontSize: '0.8rem'}}>({new Date(n.timestamp).toLocaleString()})</span>: {n.message}
                           </li>
                        ))}
                      </ul>
                    </div>
                )}
                                {/* ---------------- ACTIONS ---------------- */}
                {currentUserRole !== 'VIEWER' && (
                    <div style={{ marginTop: '1rem', padding: '1rem', background: '#f8fafc', borderRadius: '8px', border: '1px solid #e2e8f0' }}>
                        
                        {/* Inline Form Rendering based on activeAction */}
                        {activeAction && (
                            <div style={{ marginBottom: '1rem', padding: '1rem', background: 'white', borderRadius: '6px', border: '1px solid #cbd5e1' }}>
                                <h4 style={{ marginTop: 0, marginBottom: '0.75rem', color: '#1e293b' }}>{activeAction} Action</h4>
                                
                                {activeAction === 'Override' && (
                                    <div style={{ marginBottom: '0.75rem' }}>
                                        <label style={{ display: 'block', fontSize: '0.85rem', marginBottom: '0.25rem' }}>Select Unmatched Transaction</label>
                                        <select 
                                            value={overrideSelection} 
                                            onChange={e => setOverrideSelection(e.target.value)}
                                            style={{ width: '100%', padding: '0.5rem', borderRadius: '4px', border: '1px solid #cbd5e1' }}
                                        >
                                            <option value="">-- Select Transaction --</option>
                                            {data?.unmatched?.map(u => (
                                                <option key={u.group_id} value={u.group_id}>{u.raw?.id || u.group_id} - ₹{u.raw?.amount}</option>
                                            ))}
                                        </select>
                                    </div>
                                )}
                                
                                {activeAction === 'Valid Difference' && (
                                    <div style={{ marginBottom: '0.75rem' }}>
                                        <label style={{ display: 'block', fontSize: '0.85rem', marginBottom: '0.25rem' }}>Category</label>
                                        <select 
                                            value={actionCategory} 
                                            onChange={e => setActionCategory(e.target.value)}
                                            style={{ width: '100%', padding: '0.5rem', borderRadius: '4px', border: '1px solid #cbd5e1' }}
                                        >
                                            <option value="">-- Select Category --</option>
                                            <option value="Fee">Gateway Fee</option>
                                            <option value="Refund">Refund</option>
                                            <option value="Tax">Tax</option>
                                            <option value="Timing Delay">Timing Delay</option>
                                            <option value="Other">Other</option>
                                        </select>
                                    </div>
                                )}
                                
                                {activeAction === 'Escalate' && (
                                    <div style={{ marginBottom: '0.75rem' }}>
                                        <label style={{ display: 'block', fontSize: '0.85rem', marginBottom: '0.25rem' }}>Urgency Level</label>
                                        <select 
                                            value={actionCategory} 
                                            onChange={e => setActionCategory(e.target.value)}
                                            style={{ width: '100%', padding: '0.5rem', borderRadius: '4px', border: '1px solid #cbd5e1' }}
                                        >
                                            <option value="Normal">Normal</option>
                                            <option value="High">High</option>
                                        </select>
                                    </div>
                                )}

                                <div style={{ marginBottom: '0.75rem' }}>
                                    <label style={{ display: 'block', fontSize: '0.85rem', marginBottom: '0.25rem' }}>
                                        {activeAction === 'Add Note' ? 'Note Details' : 'Reason / Justification'}
                                    </label>
                                    <textarea 
                                        value={actionInput} 
                                        onChange={e => setActionInput(e.target.value)}
                                        placeholder="Enter details here..."
                                        style={{ width: '100%', padding: '0.5rem', borderRadius: '4px', border: '1px solid #cbd5e1', minHeight: '60px' }}
                                    />
                                </div>
                                
                                <div style={{ display: 'flex', gap: '0.5rem', justifyContent: 'flex-end' }}>
                                    <button 
                                        className="btn-secondary" 
                                        onClick={() => { setActiveAction(null); setActionInput(''); setActionCategory(''); setOverrideSelection(''); }}
                                        disabled={isActionLoading}
                                    >Cancel</button>
                                    <button 
                                        className="btn-primary" 
                                        disabled={isActionLoading || (!actionInput.trim() && activeAction !== 'Valid Difference')} // Require input
                                        onClick={() => {
                                            const reasonText = (actionCategory ? `[${actionCategory}] ` : '') + actionInput;
                                            
                                            if (activeAction === 'Override' && !overrideSelection) {
                                                alert("Please select a transaction to match with.");
                                                return;
                                            }
                                            
                                            if (activeAction === 'Escalate') {
                                                console.log(`[ESCALATION NOTIFICATION] Sending email/alert for ${selectedException.group_id} - Urgency: ${actionCategory || 'Normal'}`);
                                            }

                                            if (activeAction === 'Add Note') {
                                                handleResolutionAction(selectedException, selectedException.investigation_state?.resolution || 'UNKNOWN', 'Added Note', actionInput);
                                            } else if (activeAction === 'Override') {
                                                handleResolutionAction(selectedException, activeAction, `Matched manually to ${overrideSelection} - Reason: ${reasonText}`);
                                            } else {
                                                handleResolutionAction(selectedException, activeAction, reasonText, activeAction === 'Escalate' ? reasonText : null);
                                            }
                                        }}
                                    >Confirm {activeAction}</button>
                                </div>
                            </div>
                        )}

                        {/* Action Buttons */}
                        <div style={{display: 'flex', gap: '0.5rem', flexWrap: 'wrap', opacity: activeAction ? 0.5 : 1, pointerEvents: activeAction ? 'none' : 'auto'}}>
                            <button className="btn-primary" onClick={() => { 
                                handleResolutionAction(selectedException, 'Approve', 'Approved AI Decision'); 
                            }}>Approve</button>
                            
                            <button className="btn-secondary" style={{borderColor: '#ef4444', color: '#ef4444'}} onClick={() => {
                                setActiveAction('Reject');
                            }}>Reject</button>
                            
                            <button className="btn-secondary" onClick={() => {
                                setActiveAction('Override');
                            }}>Override</button>
                            
                            <button className="btn-secondary" onClick={() => {
                                setActiveAction('Valid Difference');
                            }}>Valid Difference</button>
                            
                            <button className="btn-secondary" onClick={() => {
                                setActionCategory('Normal');
                                setActiveAction('Escalate');
                            }}>Escalate</button>
                            
                            <button className="btn-secondary" onClick={() => {
                                setActiveAction('Request Info');
                            }}>Request Info</button>
                            
                            <button className="btn-secondary" onClick={() => {
                                setActiveAction('Add Note');
                            }}>+ Add Note</button>
                        </div>
                    </div>
                )}

                </div>
              </div>
            </div>
          )}

          {/* Ask AI Chat Section */}
          <div className="chat-container">
            <div className="chat-header">
              <h3>Ask AI About This Reconciliation</h3>
            </div>
            
            <div className="chat-history">
              {chatHistory.length === 0 ? (
                <div className="chat-empty-state">
                  <p>Ask a question about the reconciliation data above to get an instant AI analysis.</p>
                </div>
              ) : (
                chatHistory.map((msg, idx) => (
                  <div key={idx} className={`chat-message ${msg.role === 'user' ? 'message-user' : 'message-ai'}`}>
                    <div className="message-bubble">
                      {msg.text}
                    </div>
                  </div>
                ))
              )}
              {isChatLoading && (
                <div className="chat-message message-ai">
                  <div className="message-bubble thinking">Thinking...</div>
                </div>
              )}
            </div>
            
            <div className="chat-suggested">
              {suggestedQuestions.map((q, i) => (
                <button key={i} className="chip" onClick={() => handleAskAI(q)} disabled={isChatLoading}>
                  {q}
                </button>
              ))}
            </div>
            
            <div className="chat-input-area">
              <input 
                type="text" 
                placeholder="Ask a question..." 
                value={chatInput} 
                onChange={(e) => setChatInput(e.target.value)}
                onKeyPress={(e) => e.key === 'Enter' && handleAskAI(chatInput)}
                disabled={isChatLoading}
                className="chat-input"
              />
              <button 
                className="btn-primary chat-send-btn" 
                onClick={() => handleAskAI(chatInput)}
                disabled={isChatLoading || !chatInput.trim()}
              >
                Ask
              </button>
            </div>
          </div>
        </>
      )}
    </div>
      </main>
    </div>
  );
}

export default App;
