import React, { useState } from 'react';
import axios from 'axios';
import { BarChart, Bar, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import './App.css';

function App() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [selectedException, setSelectedException] = useState(null);
  const [evalData, setEvalData] = useState(null);
  const [evalError, setEvalError] = useState(null);
  const [forecastData, setForecastData] = useState(null);
  const [forecastError, setForecastError] = useState(null);
  
  // Chat States
  const [chatHistory, setChatHistory] = useState([]);
  const [chatInput, setChatInput] = useState('');
  const [isChatLoading, setIsChatLoading] = useState(false);
  
  const suggestedQuestions = [
    "Why do I have so many unmatched records?",
    "What's causing most fuzzy matches?",
    "Summarize today's reconciliation in simple terms",
    "Which category needs my attention most?"
  ];
  
  // Filter States
  const [filterType, setFilterType] = useState('All');
  const [filterSource, setFilterSource] = useState('All');
  const [searchQuery, setSearchQuery] = useState('');

  const closeModal = () => setSelectedException(null);

  const runReconciliation = async () => {
    setLoading(true);
    setError(null);
    setEvalData(null);
    setEvalError(null);
    try {
      // Node.js backend ko call kar rahe hain (FastAPI directly nahi)
      const response = await axios.post('http://localhost:5000/api/reconcile');
      if (response.data.success) {
        setData(response.data.data);
        
        // Chain the evaluation call
        try {
          const evalResponse = await axios.post('http://localhost:5000/api/evaluate', response.data.data);
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
          const history = [];
          (response.data.data.fully_matched || []).forEach(item => {
            if(item.settlement && item.settlement.settlement_date && item.settlement.amount) {
              history.push({ date: item.settlement.settlement_date, amount: parseFloat(item.settlement.amount) });
            }
          });
          (response.data.data.fuzzy_matched || []).forEach(item => {
            if(item.settlement && item.settlement.settlement_date && item.settlement.amount) {
              history.push({ date: item.settlement.settlement_date, amount: parseFloat(item.settlement.amount) });
            }
          });

          const forecastResponse = await axios.post('http://localhost:5000/api/forecast', { history });
          
          if (forecastResponse.data && forecastResponse.data.forecast) {
            setForecastData({
              mode: 'ai',
              data: forecastResponse.data.forecast
            });
          } else {
            throw new Error('Forecast failed');
          }
        } catch (e) {
          // Fallback simple average calculation
          const history = [];
          (response.data.data.fully_matched || []).concat(response.data.data.fuzzy_matched || []).forEach(item => {
            if (item.settlement?.settlement_date && item.settlement?.amount) {
              history.push({ date: item.settlement.settlement_date, amount: parseFloat(item.settlement.amount) });
            }
          });
          
          if(history.length > 0) {
            history.sort((a,b) => new Date(b.date) - new Date(a.date));
            const recent = history.slice(0, 7);
            const sum = recent.reduce((acc, val) => acc + val.amount, 0);
            const avg = sum / recent.length;
            
            const lastDate = new Date();
            const forecastArr = [];
            for(let i=1; i<=7; i++) {
              const d = new Date(lastDate);
              d.setDate(d.getDate() + i);
              forecastArr.push({
                date: d.toISOString().split('T')[0],
                predicted_amount: Math.round(avg),
                confidence_note: "Fallback average"
              });
            }
            
            setForecastData({
              mode: 'fallback',
              data: forecastArr
            });
          } else {
             setForecastError('Not enough data for forecast');
          }
        }
      }
    } catch (err) {
      setError(
        err.response?.data?.message || err.message || 'An error occurred during reconciliation'
      );
    } finally {
      setLoading(false);
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
    
    const fullyMatched = (data.fully_matched || []).map(item => ({
      type: 'Fully Matched',
      source: 'Multiple (Bank/Settle/Ledger)',
      date: item.bank?.date || item.settlement?.settlement_date || 'N/A',
      amount: item.bank?.amount || item.settlement?.amount || 'N/A',
      reason: 'Perfect Match',
      confidence: 100,
      raw: item
    }));
    
    const fuzzy = (data.fuzzy_matched || []).map(item => ({
      type: 'Fuzzy Matched',
      source: 'Multiple (Bank/Settle/Ledger)',
      date: item.bank?.date || item.settlement?.settlement_date || 'N/A',
      amount: item.bank?.amount || item.settlement?.amount || 'N/A',
      reason: item.ai_reason || 'Needs Review',
      confidence: item.confidence_score,
      raw: item
    }));
    
    const needsReview = (data.needs_review || []).map(item => ({
      type: 'Needs Review',
      source: 'Multiple (Bank/Settle/Ledger)',
      date: item.bank?.date || item.settlement?.settlement_date || 'N/A',
      amount: item.bank?.amount || item.settlement?.amount || 'N/A',
      reason: item.ai_reason || 'Low confidence match',
      confidence: item.confidence_score,
      raw: item
    }));
    
    const unmatched = (data.unmatched || []).map(item => ({
      type: 'Unmatched',
      source: item.source,
      date: item.record?.date || item.record?.settlement_date || item.record?.invoice_date || 'N/A',
      amount: item.record?.amount || 'N/A',
      reason: item.ai_reason || 'Missing in other sources',
      confidence: null,
      raw: item
    }));
    
    return [...fullyMatched, ...fuzzy, ...needsReview, ...unmatched];
  };

  const getFilteredList = () => {
    let list = getMasterList();
    
    if (filterType !== 'All') {
      list = list.filter(item => item.type === filterType);
    } else {
      // By default when "All" is selected, maybe hide "Fully Matched" so table remains an "Exceptions" table, 
      // but user requested "All" to be default in a dropdown that includes Fully Matched. 
      // Let's show all if 'All' is selected.
    }
    
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
      list = list.filter(item => 
        String(item.amount).toLowerCase().includes(q) || 
        String(item.date).toLowerCase().includes(q)
      );
    }
    
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
      const payload = {
        question: question,
        context_data: {
          summary: data.summary,
          evaluation: evalData || null,
          fuzzy_matched: data.fuzzy_matched || [],
          needs_review: data.needs_review || [],
          unmatched: data.unmatched || []
        }
      };
      
      const response = await axios.post('http://localhost:5000/api/ask', payload);
      
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
    <div className="container">
      <header className="header">
        <h1 className="title">Finance Reconciliation Dashboard</h1>
        <div style={{ display: 'flex', gap: '1rem', alignItems: 'center' }}>
          {data && (
            <button className="btn-secondary" onClick={downloadCSV}>
              Download Report
            </button>
          )}
          <button 
            className="btn-primary" 
            onClick={runReconciliation} 
            disabled={loading}
          >
            {loading ? 'Reconciling Data...' : 'Run Reconciliation'}
          </button>
        </div>
      </header>

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
          <p>AI is matching financial records. This may take a few seconds.</p>
        </div>
      )}

      {data && !loading && (
        <>
          <div className="dashboard-grid">
            <div className="card">
              <h3 className="card-title">Total Records</h3>
              <p className="card-value value-neutral">{data.summary.total_records}</p>
              <small style={{ color: '#64748b' }}>(Sum of all sources)</small>
            </div>
            <div className="card">
              <h3 className="card-title">Fully Matched</h3>
              <p className="card-value value-success">
                {Math.round((data.summary.fully_matched / (data.summary.total_records / 3)) * 100) || 0}%
              </p>
              <small style={{ color: '#64748b' }}>({data.summary.fully_matched} matched groups)</small>
            </div>
            <div className="card">
              <h3 className="card-title">Fuzzy Matched</h3>
              <p className="card-value value-warning">
                {Math.round((data.summary.fuzzy_matched / (data.summary.total_records / 3)) * 100) || 0}%
              </p>
              <small style={{ color: '#64748b' }}>({data.summary.fuzzy_matched} high confidence)</small>
            </div>
            <div className="card">
              <h3 className="card-title">Needs Review</h3>
              <p className="card-value" style={{ color: '#f97316', fontSize: '2rem', fontWeight: '700', marginBottom: '0.5rem' }}>
                {Math.round((data.summary.needs_review / (data.summary.total_records / 3)) * 100) || 0}%
              </p>
              <small style={{ color: '#64748b' }}>({data.summary.needs_review} partial matches)</small>
            </div>
            <div className="card">
              <h3 className="card-title">Unmatched</h3>
              <p className="card-value value-danger">
                {Math.round((data.summary.unmatched / data.summary.total_records) * 100) || 0}%
              </p>
              <small style={{ color: '#64748b' }}>({data.summary.unmatched} individual records)</small>
            </div>
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
          <div className="evaluation-panel">
            <h3 style={{ marginTop: 0, marginBottom: '1.5rem', color: '#1e293b' }}>Model Evaluation & Accuracy</h3>
            {evalError ? (
              <div className="eval-error-message">
                <p>{evalError}</p>
              </div>
            ) : evalData ? (
              <div className="eval-content">
                <div className="eval-overall">
                  <h4>Overall Model Accuracy</h4>
                  <div className={`eval-big-number ${evalData.overall_accuracy >= 85 ? 'text-green' : evalData.overall_accuracy >= 70 ? 'text-orange' : 'text-red'}`}>
                    {evalData.overall_accuracy}%
                  </div>
                </div>
                
                <div className="eval-cards-row">
                  <div className="eval-card">
                    <h5>Fully Matched Accuracy</h5>
                    <p>{evalData.category_breakdown?.['Fully Matched']?.accuracy || 0}%</p>
                  </div>
                  <div className="eval-card">
                    <h5>Fuzzy Matched Accuracy</h5>
                    <p>{evalData.category_breakdown?.['Fuzzy Matched']?.accuracy || 0}%</p>
                  </div>
                  <div className="eval-card">
                    <h5>Unmatched Detection Accuracy</h5>
                    <p>{evalData.category_breakdown?.['Unmatched']?.accuracy || 0}%</p>
                  </div>
                </div>

                <div className="eval-matrix-container">
                  <h5>Confusion Matrix</h5>
                  <table className="confusion-matrix">
                    <thead>
                      <tr>
                        <th>Actual \ Predicted</th>
                        <th>Fully Matched</th>
                        <th>Fuzzy Matched</th>
                        <th>Unmatched</th>
                      </tr>
                    </thead>
                    <tbody>
                      {['Fully Matched', 'Fuzzy Matched', 'Unmatched'].map(actual => (
                        <tr key={actual}>
                          <td><strong>{actual}</strong></td>
                          {['Fully Matched', 'Fuzzy Matched', 'Unmatched'].map(predicted => (
                            <td key={predicted}>
                              {evalData.confusion_matrix?.[actual]?.[predicted] || 0}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                {evalData.misclassified_examples && evalData.misclassified_examples.length > 0 && (
                  <details className="eval-misclassified">
                    <summary>View Misclassified Examples</summary>
                    <div className="misclassified-list">
                      {evalData.misclassified_examples.map((ex, idx) => (
                        <div key={idx} className="misclassified-item">
                          <span className="group-id"><strong>Group:</strong> {ex.group_id}</span>
                          <span className="pred"><strong>System Predicted:</strong> {ex.predicted}</span>
                          <span className="expected"><strong>Actually:</strong> {ex.expected}</span>
                        </div>
                      ))}
                    </div>
                  </details>
                )}
              </div>
            ) : (
              <div className="eval-loading">
                <p>Evaluating accuracy...</p>
              </div>
            )}
          </div>

          {/* AI Cash Flow Forecast Panel */}
          <div className="forecast-panel">
            <h3 style={{ marginTop: 0, marginBottom: '1.5rem', color: '#1e293b' }}>AI Cash Flow Forecast</h3>
            {forecastError ? (
              <div className="forecast-error-message">
                <p>{forecastError}</p>
              </div>
            ) : forecastData ? (
              <div className="forecast-content">
                <div className="forecast-summary">
                  <h4>Expected inflow next 7 days: ₹{forecastData.data.reduce((acc, curr) => acc + (Number(curr.predicted_amount) || 0), 0).toLocaleString('en-IN')} (based on {forecastData.mode === 'ai' ? 'AI analysis of settlement patterns' : 'simple average projection'})</h4>
                </div>
                
                <div style={{ height: '300px' }}>
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={forecastData.data}>
                      <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
                      <XAxis dataKey="date" axisLine={false} tickLine={false} />
                      <YAxis axisLine={false} tickLine={false} />
                      <Tooltip cursor={{ fill: '#f1f5f9' }} />
                      <Line type="monotone" dataKey="predicted_amount" stroke="#2563eb" strokeWidth={3} dot={{ r: 4 }} activeDot={{ r: 6 }} />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
                
                <p className="forecast-disclaimer">
                  {forecastData.mode === 'ai' 
                    ? "AI-generated forecast based on historical settlement patterns — indicative only"
                    : "Fallback: simple average projection"}
                </p>
              </div>
            ) : (
              <div className="forecast-loading">
                <p>Generating cash flow forecast...</p>
              </div>
            )}
          </div>

          <div className="exceptions-container">
            <div className="exceptions-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '1rem' }}>
              <h3 className="exceptions-title">Exceptions & AI Analysis</h3>
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
            <div className="table-wrapper">
              <table>
                <thead>
                  <tr>
                    <th>Type</th>
                    <th>Source</th>
                    <th>Date</th>
                    <th>Amount</th>
                    <th>AI Reason</th>
                  </tr>
                </thead>
                <tbody>
                  {getFilteredList().map((exp, idx) => (
                    <tr key={idx} onClick={() => setSelectedException(exp)} className="clickable-row">
                      <td>
                        <span className={`badge ${exp.type === 'Fully Matched' ? 'badge-success' : (exp.type === 'Fuzzy Matched' ? 'badge-warning' : (exp.type === 'Needs Review' ? 'badge-primary' : 'badge-danger'))}`} style={exp.type === 'Needs Review' ? {backgroundColor: '#f97316', color: 'white'} : (exp.type === 'Fully Matched' ? {backgroundColor: '#10b981', color: 'white'} : {})}>
                          {exp.type}
                        </span>
                      </td>
                      <td style={{ textTransform: 'capitalize' }}>{exp.source.replace(/_/g, ' ')}</td>
                      <td>{exp.date}</td>
                      <td>₹{exp.amount}</td>
                      <td>
                        <strong style={{ display: 'block', marginBottom: '4px' }}>{exp.reason}</strong>
                        {exp.confidence && (
                          <span style={{ fontSize: '0.75rem', color: '#64748b' }}>
                            Confidence: {Math.round(exp.confidence)}%
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}
                  {getFilteredList().length === 0 && (
                    <tr>
                      <td colSpan="5" style={{ textAlign: 'center', color: '#64748b', padding: '3rem' }}>
                        No matching records found
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>

          {selectedException && (
            <div className="modal-backdrop" onClick={closeModal}>
              <div className="modal-content" onClick={(e) => e.stopPropagation()}>
                <div className="modal-header">
                  <h2>Exception Details</h2>
                  <button className="close-btn" onClick={closeModal}>&times;</button>
                </div>
                
                <div className="modal-badges">
                  <span className={`badge ${selectedException.type === 'Fuzzy Matched' ? 'badge-warning' : (selectedException.type === 'Needs Review' ? 'badge-primary' : 'badge-danger')}`} style={selectedException.type === 'Needs Review' ? {backgroundColor: '#f97316', color: 'white'} : {}}>
                    {selectedException.type}
                  </span>
                  {selectedException.confidence && (
                    <span className="badge" style={{ backgroundColor: '#e2e8f0', color: '#1e293b', marginLeft: '0.5rem' }}>
                      Confidence: {Math.round(selectedException.confidence)}%
                    </span>
                  )}
                </div>
                
                <div className="modal-reason">
                  <strong>AI Reason:</strong> {selectedException.reason}
                </div>

                <div className="modal-grid">
                  <div className="modal-column">
                    <h3>Bank Statement</h3>
                    {selectedException.raw.bank || (selectedException.raw.source === 'bank_statement' && selectedException.raw.record) ? (
                      <div className="record-details">
                        {(() => {
                          const record = selectedException.raw.bank || selectedException.raw.record;
                          return (
                            <>
                              <p><strong>Date:</strong> {record.date}</p>
                              <p><strong>Amount:</strong> ₹{record.amount}</p>
                              <p><strong>UTR:</strong> {record.utr_number}</p>
                              <p><strong>Narration:</strong> {record.narration}</p>
                            </>
                          );
                        })()}
                      </div>
                    ) : (
                      <div className="record-missing">Not Found</div>
                    )}
                  </div>

                  <div className="modal-column">
                    <h3>Settlement</h3>
                    {selectedException.raw.settlement || (selectedException.raw.source === 'settlement' && selectedException.raw.record) ? (
                      <div className="record-details">
                        {(() => {
                          const record = selectedException.raw.settlement || selectedException.raw.record;
                          return (
                            <>
                              <p><strong>Date:</strong> {record.settlement_date}</p>
                              <p><strong>Amount:</strong> ₹{record.amount}</p>
                              <p><strong>UTR:</strong> {record.utr_number}</p>
                              <p><strong>Settle ID:</strong> {record.settlement_id}</p>
                              <p><strong>Merchant:</strong> {record.merchant_name || 'N/A'}</p>
                            </>
                          );
                        })()}
                      </div>
                    ) : (
                      <div className="record-missing">Not Found</div>
                    )}
                  </div>

                  <div className="modal-column">
                    <h3>Internal Ledger</h3>
                    {selectedException.raw.ledger || (selectedException.raw.source === 'ledger' && selectedException.raw.record) ? (
                      <div className="record-details">
                        {(() => {
                          const record = selectedException.raw.ledger || selectedException.raw.record;
                          return (
                            <>
                              <p><strong>Date:</strong> {record.invoice_date}</p>
                              <p><strong>Amount:</strong> ₹{record.amount}</p>
                              <p><strong>Settle Ref:</strong> {record.settlement_ref}</p>
                              <p><strong>Invoice ID:</strong> {record.invoice_id}</p>
                              <p><strong>Customer:</strong> {record.customer_name}</p>
                            </>
                          );
                        })()}
                      </div>
                    ) : (
                      <div className="record-missing">Not Found</div>
                    )}
                  </div>
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
  );
}

export default App;
