// Enhanced Time Period Analysis Functions with Full Backend Integration

let currentAnalysisData = null;
let analysisChart = null;
let categoryChart = null;

// Utility functions
function formatNumber(num) {
    if (num >= 1000000) {
        return (num / 1000000).toFixed(1) + 'M';
    } else if (num >= 1000) {
        return (num / 1000).toFixed(1) + 'K';
    }
    return num.toFixed(0);
}

function formatCurrency(amount) {
    return new Intl.NumberFormat('en-US', {
        style: 'currency',
        currency: 'USD'
    }).format(amount);
}

// Main Analysis Function
async function runAnalysis(event) {
    event.preventDefault();
    
    const form = event.target;
    const formData = new FormData(form);
    
    // Get form values
    const startDate = formData.get('analysisStartDate') || null;
    const endDate = formData.get('analysisEndDate') || null;
    const groupBy = document.getElementById('analysisGroupBy').value;
    const showCategories = document.getElementById('showCategories').checked;
    const showComparison = document.getElementById('showComparison').checked;
    const trendCategory = document.getElementById('analysisTrendCategory').value;
    const analysisName = formData.get('analysisName') || null;
    
    // Check if we have uploaded files or processed data
    const csvFilesInput = document.getElementById('csvFiles');
    const hasCurrentFiles = csvFilesInput && csvFilesInput.files && csvFilesInput.files.length > 0;
    const hasProcessedData = window.lastProcessedFiles && window.lastProcessedFiles.length > 0;
    
    if (!hasCurrentFiles && !hasProcessedData) {
        showMessage('Please upload CSV files in the Import Transactions tab first before running analysis.', 'warning');
        showTab('transactions');
        return;
    }
    
    try {
        // Show loading state
        setAnalysisLoading(true);
        
        let filesToProcess = [];
        
        // Determine which files to use
        if (hasCurrentFiles) {
            // Use currently selected files
            for (let i = 0; i < csvFilesInput.files.length; i++) {
                filesToProcess.push(csvFilesInput.files[i]);
            }
            console.log('🔍 Using currently selected files:', filesToProcess.length);
        } else if (hasProcessedData) {
            // Use previously processed files (re-upload them)
            for (let fileData of window.lastProcessedFiles) {
                // Create a new File object from stored data
                const file = new File([fileData.content], fileData.name, { type: 'text/csv' });
                filesToProcess.push(file);
            }
            console.log('🔍 Using previously processed files:', filesToProcess.length);
        }
        
        if (filesToProcess.length === 0) {
            throw new Error('No files available for analysis');
        }
        
        // Prepare files for analysis
        const formDataForUpload = new FormData();
        
        // Add all files
        filesToProcess.forEach((file, index) => {
            formDataForUpload.append('files', file);
        });
        
        // Add analysis parameters
        formDataForUpload.append('analysis_mode', 'true');
        formDataForUpload.append('start_date', startDate || '');
        formDataForUpload.append('end_date', endDate || '');
        formDataForUpload.append('group_by', groupBy);
        formDataForUpload.append('show_categories', showCategories);
        formDataForUpload.append('show_comparison', showComparison);
        formDataForUpload.append('trend_category', trendCategory === 'total' ? '' : trendCategory);
        formDataForUpload.append('analysis_name', analysisName || '');
        
        // Call the enhanced analysis endpoint
        const response = await fetch('/api/run-time-period-analysis', {
            method: 'POST',
            body: formDataForUpload
        });
        
        const result = await response.json();
        
        if (result.success) {
            currentAnalysisData = result.data;
            displayAnalysisResults(result.data);
            showMessage('Analysis completed successfully!', 'success');
        } else {
            throw new Error(result.error);
        }
        
    } catch (err) {
        console.error('Analysis error:', err);
        showMessage('Error running analysis: ' + err.message, 'error');
    } finally {
        setAnalysisLoading(false);
    }
}

function setAnalysisLoading(isLoading) {
    const submitButton = document.querySelector('#analysis-tab form button[type="submit"]');
    const resultsDiv = document.getElementById('analysisResults');
    
    if (submitButton) {
        submitButton.disabled = isLoading;
        submitButton.innerHTML = isLoading ? 
            '<span class="loading-spinner" style="margin-right: 0.5rem;"></span>Running Analysis...' :
            'Run Analysis';
    }
    
    if (isLoading && resultsDiv) {
        resultsDiv.innerHTML = `
            <div class="card">
                <div class="loading">
                    <div class="loading-spinner"></div>
                    <p>Analyzing transaction data...</p>
                </div>
            </div>
        `;
        resultsDiv.style.display = 'block';
        resultsDiv.scrollIntoView({ behavior: 'smooth' });
    }
}

function displayAnalysisResults(data) {
    const resultsDiv = document.getElementById('analysisResults');
    if (!resultsDiv) return;
    
    resultsDiv.innerHTML = `
        <div class="card">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 1.5rem;">
                <h3>📊 Time Period Analysis Results</h3>
                <div>
                    <button class="btn btn-secondary btn-small" onclick="exportAnalysisData()">
                        📄 Export Data
                    </button>
                    ${data.analysis_name ? `
                        <button class="btn btn-success btn-small" onclick="saveCurrentAnalysis()">
                            💾 Save Analysis
                        </button>
                    ` : ''}
                </div>
            </div>
            
            ${data.metadata ? `
                <div class="analysis-metadata" style="background: #f8f9fa; padding: 1rem; border-radius: 6px; margin-bottom: 1.5rem;">
                    <h4 style="margin: 0 0 0.5rem 0; font-size: 0.9rem; color: #666;">Analysis Parameters</h4>
                    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 0.5rem; font-size: 0.85rem;">
                        ${data.metadata.date_range ? `<div><strong>Date Range:</strong> ${data.metadata.date_range}</div>` : ''}
                        ${data.metadata.group_by ? `<div><strong>Grouped By:</strong> ${data.metadata.group_by}</div>` : ''}
                        ${data.metadata.file_count ? `<div><strong>Files Processed:</strong> ${data.metadata.file_count}</div>` : ''}
                        ${data.metadata.total_transactions ? `<div><strong>Total Transactions:</strong> ${data.metadata.total_transactions}</div>` : ''}
                    </div>
                </div>
            ` : ''}
            
            <div id="analysisCharts"></div>
            <div id="analysisTables"></div>
            <div id="analysisTrends"></div>
        </div>
    `;
    
    // Display different sections of the analysis
    displayAnalysisCharts(data);
    displayAnalysisTables(data);
    displayAnalysisTrends(data);
    
    resultsDiv.style.display = 'block';
    resultsDiv.scrollIntoView({ behavior: 'smooth' });
}

function displayAnalysisCharts(data) {
    const chartsDiv = document.getElementById('analysisCharts');
    if (!chartsDiv || !data.period_analysis) return;
    
    const periods = Object.keys(data.period_analysis).sort();
    const totals = periods.map(period => data.period_analysis[period].total_spending);
    
    chartsDiv.innerHTML = `
        <div class="analysis-charts">
            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 2rem; margin-bottom: 2rem;">
                <div class="chart-container">
                    <h4 style="text-align: center; margin-bottom: 1rem;">📈 Spending Over Time</h4>
                    <canvas id="spendingChart" width="400" height="300"></canvas>
                </div>
                <div class="chart-container">
                    <h4 style="text-align: center; margin-bottom: 1rem;">🥧 Category Breakdown (Latest Period)</h4>
                    <canvas id="categoryChart" width="400" height="300"></canvas>
                </div>
            </div>
        </div>
    `;
    
    // Create spending over time chart
    createSpendingChart(periods, totals);
    
    // Create category breakdown chart for latest period
    if (periods.length > 0) {
        const latestPeriod = periods[periods.length - 1];
        const latestCategories = data.period_analysis[latestPeriod].categories;
        createCategoryChart(latestCategories);
    }
}

function createSpendingChart(periods, totals) {
    const canvas = document.getElementById('spendingChart');
    if (!canvas) return;
    
    const ctx = canvas.getContext('2d');
    
    // Destroy existing chart if it exists
    if (analysisChart) {
        analysisChart.destroy();
    }
    
    // Simple canvas-based chart implementation
    drawLineChart(ctx, {
        labels: periods,
        data: totals,
        title: 'Total Spending by Period',
        color: '#3b82f6',
        fillColor: '#3b82f620'
    });
}

function createCategoryChart(categories) {
    const canvas = document.getElementById('categoryChart');
    if (!canvas) return;
    
    const ctx = canvas.getContext('2d');
    
    // Destroy existing chart if it exists
    if (categoryChart) {
        categoryChart.destroy();
    }
    
    // Filter out zero values
    const filteredCategories = Object.entries(categories)
        .filter(([_, value]) => value > 0)
        .sort(([_, a], [__, b]) => b - a);
    
    const labels = filteredCategories.map(([label, _]) => label);
    const data = filteredCategories.map(([_, value]) => value);
    
    drawPieChart(ctx, {
        labels: labels,
        data: data,
        colors: ['#ef4444', '#f97316', '#eab308', '#22c55e', '#3b82f6', '#8b5cf6', '#ec4899']
    });
}

function drawLineChart(ctx, config) {
    const canvas = ctx.canvas;
    const width = canvas.width;
    const height = canvas.height;
    const padding = 80; // Increased padding for better label spacing
    
    // Clear canvas
    ctx.clearRect(0, 0, width, height);
    
    // Calculate bounds
    const chartWidth = width - 2 * padding;
    const chartHeight = height - 2 * padding - 40; // Extra space for rotated labels
    const maxValue = Math.max(...config.data);
    const minValue = Math.min(...config.data);
    const valueRange = maxValue - minValue || 1;
    
    // Draw grid lines
    ctx.strokeStyle = '#e5e7eb';
    ctx.lineWidth = 1;
    
    // Horizontal grid lines
    for (let i = 0; i <= 5; i++) {
        const y = padding + (i * chartHeight / 5);
        ctx.beginPath();
        ctx.moveTo(padding, y);
        ctx.lineTo(width - padding, y);
        ctx.stroke();
        
        // Y-axis labels
        const value = maxValue - (i * valueRange / 5);
        ctx.fillStyle = '#6b7280';
        ctx.font = '12px Arial';
        ctx.textAlign = 'right';
        ctx.fillText('$' + formatNumber(value), padding - 10, y + 4);
    }
    
    // Draw data line
    if (config.data.length > 1) {
        ctx.strokeStyle = config.color;
        ctx.lineWidth = 3;
        ctx.beginPath();
        
        config.data.forEach((value, index) => {
            const x = padding + (index * chartWidth / (config.data.length - 1));
            const y = padding + chartHeight - ((value - minValue) / valueRange * chartHeight);
            
            if (index === 0) {
                ctx.moveTo(x, y);
            } else {
                ctx.lineTo(x, y);
            }
        });
        
        ctx.stroke();
        
        // Draw data points
        ctx.fillStyle = config.color;
        config.data.forEach((value, index) => {
            const x = padding + (index * chartWidth / (config.data.length - 1));
            const y = padding + chartHeight - ((value - minValue) / valueRange * chartHeight);
            
            ctx.beginPath();
            ctx.arc(x, y, 4, 0, 2 * Math.PI);
            ctx.fill();
        });
    }
    
    // Draw X-axis labels with better spacing and rotation
    ctx.fillStyle = '#6b7280';
    ctx.font = '11px Arial';
    ctx.textAlign = 'center';
    
    config.labels.forEach((label, index) => {
        const x = padding + (index * chartWidth / (config.labels.length - 1));
        const y = height - padding + 35;
        
        // Save context for rotation
        ctx.save();
        ctx.translate(x, y);
        
        // Rotate labels if there are many periods to prevent overlap
        if (config.labels.length > 4) {
            ctx.rotate(-Math.PI / 4); // 45 degree rotation
            ctx.textAlign = 'right';
        }
        
        ctx.fillText(label, 0, 0);
        ctx.restore();
    });
}

function drawPieChart(ctx, config) {
    const canvas = ctx.canvas;
    const legendWidth = 150; // Space reserved for legend on the left
    const pieAreaWidth = canvas.width - legendWidth - 40; // Remaining space for pie
    const centerX = legendWidth + (pieAreaWidth / 2) + 20; // Center pie in remaining space
    const centerY = canvas.height / 2;
    const radius = Math.min(pieAreaWidth, canvas.height) / 3; // Bigger radius using available space
    
    // Clear canvas
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    
    const total = config.data.reduce((sum, value) => sum + value, 0);
    let currentAngle = -Math.PI / 2; // Start at top
    
    // Draw legend on the left side first
    const legendStartX = 20;
    const legendStartY = 50; // Start from top
    const legendItemHeight = 22;
    
    let legendIndex = 0;
    config.labels.forEach((label, index) => {
        const value = config.data[index];
        const percentage = ((value / total) * 100).toFixed(1);
        
        // Skip categories with 0 value
        if (value === 0) return;
        
        const legendY = legendStartY + (legendIndex * legendItemHeight);
        
        // Color box
        ctx.fillStyle = config.colors[index % config.colors.length];
        ctx.fillRect(legendStartX, legendY, 14, 14);
        
        // Label text
        ctx.fillStyle = '#374151';
        ctx.font = '12px Arial';
        ctx.textAlign = 'left';
        
        // Keep full label names
        const labelText = `${label}: ${percentage}%`;
        ctx.fillText(labelText, legendStartX + 20, legendY + 10);
        
        legendIndex++;
    });
    
    // Draw pie slices on the right side
    config.data.forEach((value, index) => {
        const sliceAngle = (value / total) * 2 * Math.PI;
        
        ctx.fillStyle = config.colors[index % config.colors.length];
        ctx.beginPath();
        ctx.moveTo(centerX, centerY);
        ctx.arc(centerX, centerY, radius, currentAngle, currentAngle + sliceAngle);
        ctx.closePath();
        ctx.fill();
        
        // Draw percentage labels inside slices (only for large slices)
        const percentage = ((value / total) * 100).toFixed(1);
        if (percentage > 6) { // Show labels for slices 6% or larger
            const labelAngle = currentAngle + sliceAngle / 2;
            const labelX = centerX + Math.cos(labelAngle) * (radius * 0.7);
            const labelY = centerY + Math.sin(labelAngle) * (radius * 0.7);
            
            ctx.fillStyle = '#ffffff';
            ctx.font = 'bold 12px Arial';
            ctx.textAlign = 'center';
            ctx.fillText(`${percentage}%`, labelX, labelY);
        }
        
        currentAngle += sliceAngle;
    });
}

function displayAnalysisTables(data) {
    const tablesDiv = document.getElementById('analysisTables');
    if (!tablesDiv || !data.period_analysis) return;
    
    const periods = Object.keys(data.period_analysis).sort();
    
    tablesDiv.innerHTML = `
        <div class="analysis-tables" style="margin: 2rem 0;">
            <h4 style="margin-bottom: 1rem;">📋 Period Summary</h4>
            <div style="overflow-x: auto;">
                <table class="analysis-table" style="width: 100%; border-collapse: collapse; background: white; border-radius: 6px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.1);">
                    <thead>
                        <tr style="background: #f8f9fa;">
                            <th style="padding: 1rem; text-align: left; font-weight: 600; border-bottom: 1px solid #dee2e6;">Period</th>
                            <th style="padding: 1rem; text-align: right; font-weight: 600; border-bottom: 1px solid #dee2e6;">Total Spending</th>
                            <th style="padding: 1rem; text-align: right; font-weight: 600; border-bottom: 1px solid #dee2e6;">Transactions</th>
                            <th style="padding: 1rem; text-align: right; font-weight: 600; border-bottom: 1px solid #dee2e6;">Avg/Transaction</th>
                            <th style="padding: 1rem; text-align: right; font-weight: 600; border-bottom: 1px solid #dee2e6;">Top Category</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${periods.map((period, index) => {
                            const periodData = data.period_analysis[period];
                            const topCategory = getTopCategory(periodData.categories);
                            const isLatest = index === periods.length - 1;
                            
                            return `
                                <tr style="background: ${isLatest ? '#f0f9ff' : 'white'}; ${isLatest ? 'font-weight: 500;' : ''}">
                                    <td style="padding: 1rem; border-bottom: 1px solid #dee2e6;">
                                        ${period} ${isLatest ? '<span style="color: #3b82f6; font-size: 0.75rem;">LATEST</span>' : ''}
                                    </td>
                                    <td style="padding: 1rem; text-align: right; border-bottom: 1px solid #dee2e6; font-weight: 600;">
                                        ${formatCurrency(periodData.total_spending)}
                                    </td>
                                    <td style="padding: 1rem; text-align: right; border-bottom: 1px solid #dee2e6;">
                                        ${periodData.transaction_count}
                                    </td>
                                    <td style="padding: 1rem; text-align: right; border-bottom: 1px solid #dee2e6;">
                                        ${formatCurrency(periodData.average_transaction)}
                                    </td>
                                    <td style="padding: 1rem; text-align: right; border-bottom: 1px solid #dee2e6;">
                                        ${topCategory.name}<br>
                                        <small style="color: #6b7280;">${formatCurrency(topCategory.amount)}</small>
                                    </td>
                                </tr>
                            `;
                        }).join('')}
                    </tbody>
                </table>
            </div>
            
            ${data.show_categories ? displayCategoryBreakdown(data.period_analysis) : ''}
        </div>
    `;
}

function displayCategoryBreakdown(periodAnalysis) {
    const periods = Object.keys(periodAnalysis).sort();
    const categories = ['Shopping', 'Food & Drinks', 'Services', 'Entertainment', 'Groceries', 'Other'];
    
    return `
        <div style="margin-top: 2rem;">
            <h4 style="margin-bottom: 1rem;">🏷️ Category Breakdown by Period</h4>
            <div style="overflow-x: auto;">
                <table class="analysis-table" style="width: 100%; border-collapse: collapse; background: white; border-radius: 6px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.1);">
                    <thead>
                        <tr style="background: #f8f9fa;">
                            <th style="padding: 1rem; text-align: left; font-weight: 600; border-bottom: 1px solid #dee2e6;">Period</th>
                            ${categories.map(cat => `
                                <th style="padding: 1rem; text-align: right; font-weight: 600; border-bottom: 1px solid #dee2e6; min-width: 100px;">
                                    ${cat}
                                </th>
                            `).join('')}
                        </tr>
                    </thead>
                    <tbody>
                        ${periods.map(period => {
                            const periodData = periodAnalysis[period];
                            return `
                                <tr style="background: white;">
                                    <td style="padding: 1rem; border-bottom: 1px solid #dee2e6; font-weight: 500;">
                                        ${period}
                                    </td>
                                    ${categories.map(category => {
                                        const amount = periodData.categories[category] || 0;
                                        return `
                                            <td style="padding: 1rem; text-align: right; border-bottom: 1px solid #dee2e6;">
                                                ${amount > 0 ? formatCurrency(amount) : '-'}
                                            </td>
                                        `;
                                    }).join('')}
                                </tr>
                            `;
                        }).join('')}
                        <tr style="background: #f8f9fa; font-weight: 600;">
                            <td style="padding: 1rem; border-bottom: 1px solid #dee2e6;">
                                TOTALS
                            </td>
                            ${categories.map(category => {
                                const total = periods.reduce((sum, period) => 
                                    sum + (periodAnalysis[period].categories[category] || 0), 0
                                );
                                return `
                                    <td style="padding: 1rem; text-align: right; border-bottom: 1px solid #dee2e6;">
                                        ${total > 0 ? formatCurrency(total) : '-'}
                                    </td>
                                `;
                            }).join('')}
                        </tr>
                    </tbody>
                </table>
            </div>
        </div>
    `;
}

function displayAnalysisTrends(data) {
    const trendsDiv = document.getElementById('analysisTrends');
    if (!trendsDiv || !data.trends) return;
    
    trendsDiv.innerHTML = `
        <div class="analysis-trends" style="margin: 2rem 0;">
            <h4 style="margin-bottom: 1rem;">📈 Trend Analysis</h4>
            <div style="background: white; padding: 1.5rem; border-radius: 6px; box-shadow: 0 1px 3px rgba(0,0,0,0.1);">
                ${data.trends.map(trend => `
                    <div style="margin-bottom: 1rem; padding-bottom: 1rem; border-bottom: 1px solid #e5e7eb;">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem;">
                            <h5 style="margin: 0; color: #374151;">${trend.category || 'Total Spending'}</h5>
                            <span class="trend-indicator ${trend.direction}" style="font-size: 1.5rem;">
                                ${getTrendIcon(trend.direction)}
                            </span>
                        </div>
                        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 1rem; font-size: 0.9rem;">
                            <div>
                                <strong>Direction:</strong> ${trend.direction_text}
                            </div>
                            <div>
                                <strong>Change:</strong> ${trend.change_text}
                            </div>
                            <div>
                                <strong>Recent Avg:</strong> ${formatCurrency(trend.recent_average)}
                            </div>
                            <div>
                                <strong>Historical Avg:</strong> ${formatCurrency(trend.historical_average)}
                            </div>
                        </div>
                    </div>
                `).join('')}
            </div>
        </div>
    `;
}

function getTopCategory(categories) {
    const entries = Object.entries(categories);
    if (entries.length === 0) return { name: 'None', amount: 0 };
    
    const sorted = entries.sort(([,a], [,b]) => b - a);
    return { name: sorted[0][0], amount: sorted[0][1] };
}

function getTrendIcon(direction) {
    switch (direction) {
        case 'increasing': return '📈';
        case 'decreasing': return '📉';
        case 'stable': return '➡️';
        default: return '📊';
    }
}

async function exportAnalysisData() {
    if (!currentAnalysisData) {
        showMessage('No analysis data to export', 'warning');
        return;
    }
    
    try {
        const dataStr = JSON.stringify(currentAnalysisData, null, 2);
        const dataBlob = new Blob([dataStr], { type: 'application/json' });
        
        const link = document.createElement('a');
        link.href = URL.createObjectURL(dataBlob);
        link.download = `analysis_${new Date().toISOString().split('T')[0]}.json`;
        link.click();
        
        showMessage('Analysis data exported successfully!', 'success');
    } catch (err) {
        showMessage('Error exporting data: ' + err.message, 'error');
    }
}

async function saveCurrentAnalysis() {
    if (!currentAnalysisData || !currentAnalysisData.analysis_name) {
        showMessage('No analysis name specified for saving', 'warning');
        return;
    }
    
    try {
        const response = await fetch('/api/save-analysis', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                name: currentAnalysisData.analysis_name,
                data: currentAnalysisData
            })
        });
        
        const result = await response.json();
        
        if (result.success) {
            showMessage('Analysis saved successfully!', 'success');
            loadStoredAnalyses(); // Refresh the historical analyses list
        } else {
            throw new Error(result.error);
        }
    } catch (err) {
        showMessage('Error saving analysis: ' + err.message, 'error');
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
            // Store for later use
            window.storedAnalyses = result.data;
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
        storedAnalysesList.innerHTML = `
            <div class="empty-state">
                <div class="empty-state-icon">🗂️</div>
                <p>No stored analyses found</p>
                <small>Run and save analyses from the Time Period Analysis tab</small>
            </div>
        `;
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
            // Display in the analysis tab
            currentAnalysisData = { 
                period_analysis: result.data,
                metadata: { analysis_name: analysisName }
            };
            
            // Switch to analysis tab and display
            showTab('analysis');
            displayAnalysisResults(currentAnalysisData);
            
            showMessage(`Loaded stored analysis: ${analysisName}`, 'success');
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
}