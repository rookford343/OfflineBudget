// Time Period Analysis Functions

// Time Period Analysis Functions
async function runAnalysis(event) {
    event.preventDefault();
    
    try {
        // Note: This would need to be implemented in the backend API
        showMessage('Time period analysis feature coming soon!', 'info');
    } catch (err) {
        showMessage('Error running analysis: ' + err.message, 'error');
    }
}

// Historical Data Functions
async function loadStoredAnalyses() {
    try {
        const response = await fetch('/api/historical-analyses');
        const result = await response.json();
        
        if (result.success) {
            displayStoredAnalyses(result.data);
            updateComparisonDropdowns(result.data);
            storedAnalyses = result.data;
        } else {
            showMessage('Error loading stored analyses: ' + result.error, 'error');
        }
    } catch (err) {
        showMessage('Error loading stored analyses: ' + err.message, 'error');
    }
}

function displayStoredAnalyses(analyses) {
    const storedAnalysesList = document.getElementById('storedAnalysesList');
    
    if (!analyses || analyses.length === 0) {
        storedAnalysesList.innerHTML = '<div class="empty-state"><div class="empty-state-icon">🗂️</div>No stored analyses found<br><small>Run and save analyses from the Time Period Analysis tab</small></div>';
        return;
    }

    storedAnalysesList.innerHTML = analyses.map(analysis => `
        <div class="list-item">
            <div class="item-info">
                <div class="item-name">${escapeHtml(analysis.name)}</div>
                <div class="item-details">
                    Created: ${new Date(analysis.created_date).toLocaleDateString()} • 
                    ${analysis.period_count} periods
                    ${analysis.metadata && Object.keys(analysis.metadata).length > 0 ? 
                        '<br>' + Object.entries(analysis.metadata).map(([k,v]) => `${k}: ${v}`).join(' • ') : ''}
                </div>
            </div>
            <div class="item-actions">
                <button class="btn btn-small" onclick="viewStoredAnalysis('${escapeHtml(analysis.name)}')">
                    👁️ View
                </button>
                <button class="btn btn-small btn-danger" onclick="deleteStoredAnalysis('${escapeHtml(analysis.name)}')">
                    🗑️ Delete
                </button>
            </div>
        </div>
    `).join('');
}

async function viewStoredAnalysis(analysisName) {
    try {
        const response = await fetch(`/api/historical-analyses/${encodeURIComponent(analysisName)}`);
        const result = await response.json();
        
        if (result.success) {
            displayAnalysisResults(result.data, `Stored Analysis: ${analysisName}`);
        } else {
            showMessage('Error loading analysis: ' + result.error, 'error');
        }
    } catch (err) {
        showMessage('Error loading analysis: ' + err.message, 'error');
    }
}

async function deleteStoredAnalysis(analysisName) {
    if (!confirm(`Are you sure you want to delete the analysis "${analysisName}"? This action cannot be undone.`)) {
        return;
    }
    
    try {
        const response = await fetch(`/api/historical-analyses/${encodeURIComponent(analysisName)}`, {
            method: 'DELETE'
        });
        
        const result = await response.json();
        
        if (result.success) {
            showMessage('Analysis deleted successfully!', 'success');
            loadStoredAnalyses(); // Refresh the list
        } else {
            showMessage('Error deleting analysis: ' + result.error, 'error');
        }
    } catch (err) {
        showMessage('Error deleting analysis: ' + err.message, 'error');
    }
}

function updateComparisonDropdowns(analyses) {
    const dropdown1 = document.getElementById('compareAnalysis1');
    const dropdown2 = document.getElementById('compareAnalysis2');
    
    [dropdown1, dropdown2].forEach(dropdown => {
        if (dropdown) {
            dropdown.innerHTML = '<option value="">Select analysis...</option>';
            analyses.forEach(analysis => {
                dropdown.innerHTML += `<option value="${escapeHtml(analysis.name)}">${escapeHtml(analysis.name)}</option>`;
            });
        }
    });
}

async function compareAnalyses(event) {
    event.preventDefault();
    
    const analysis1 = document.getElementById('compareAnalysis1')?.value;
    const analysis2 = document.getElementById('compareAnalysis2')?.value;
    
    if (!analysis1 || !analysis2) {
        showMessage('Please select two analyses to compare', 'error');
        return;
    }

    try {
        const response = await fetch('/api/compare-analyses', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                analysis1: analysis1,
                analysis2: analysis2
            })
        });

        const result = await response.json();
        
        if (result.success) {
            displayComparisonResults(result.data);
        } else {
            showMessage('Error comparing analyses: ' + result.error, 'error');
        }
    } catch (err) {
        showMessage('Error comparing analyses: ' + err.message, 'error');
    }
}

function displayAnalysisResults(data, title = 'Analysis Results') {
    const resultsDiv = document.getElementById('analysisResults') || document.getElementById('historicalResults');
    if (!resultsDiv) return;
    
    // Basic display for analysis results
    resultsDiv.innerHTML = `
        <div class="card">
            <h3>📊 ${title}</h3>
            <div class="analysis-results">
                <pre style="background: #f8f8f8; padding: 1rem; border-radius: 4px; overflow-x: auto; font-size: 0.85rem;">${JSON.stringify(data, null, 2)}</pre>
            </div>
        </div>
    `;
    
    resultsDiv.scrollIntoView({ behavior: 'smooth' });
}

function displayComparisonResults(data) {
    const resultsDiv = document.getElementById('historicalResults');
    if (!resultsDiv) return;
    
    resultsDiv.innerHTML = `
        <div class="card">
            <h3>📊 Analysis Comparison</h3>
            <p><strong>${escapeHtml(data.analysis1_name)}</strong> vs <strong>${escapeHtml(data.analysis2_name)}</strong></p>
            <p>Common periods: ${data.common_periods}</p>
            
            <div class="analysis-results">
                <table class="analysis-table" style="width: 100%; border-collapse: collapse; margin: 1rem 0;">
                    <thead>
                        <tr style="background: var(--background-color);">
                            <th style="padding: 0.75rem; text-align: left; border-bottom: 1px solid var(--border-color); font-weight: 600;">Period</th>
                            <th style="padding: 0.75rem; text-align: left; border-bottom: 1px solid var(--border-color); font-weight: 600;">${escapeHtml(data.analysis1_name)}</th>
                            <th style="padding: 0.75rem; text-align: left; border-bottom: 1px solid var(--border-color); font-weight: 600;">${escapeHtml(data.analysis2_name)}</th>
                            <th style="padding: 0.75rem; text-align: left; border-bottom: 1px solid var(--border-color); font-weight: 600;">Difference</th>
                            <th style="padding: 0.75rem; text-align: left; border-bottom: 1px solid var(--border-color); font-weight: 600;">% Change</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${data.comparisons.map(comp => `
                            <tr>
                                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">${comp.period}</td>
                                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">${formatCurrency(comp.analysis1_total)}</td>
                                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);">${formatCurrency(comp.analysis2_total)}</td>
                                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);" class="${comp.difference >= 0 ? 'status-warning' : 'status-good'}">
                                    ${formatCurrency(comp.difference)}
                                </td>
                                <td style="padding: 0.75rem; border-bottom: 1px solid var(--border-color);" class="${comp.percent_change >= 0 ? 'status-warning' : 'status-good'}">
                                    ${comp.percent_change.toFixed(1)}%
                                    <span class="trend-indicator" style="font-size: 1.2rem; margin-left: 0.5rem;">
                                        ${comp.percent_change > 0 ? '📈' : comp.percent_change < 0 ? '📉' : '➡️'}
                                    </span>
                                </td>
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            </div>
        </div>
    `;
    
    resultsDiv.scrollIntoView({ behavior: 'smooth' });
}