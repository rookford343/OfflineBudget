// Transaction Import Functions with Universal CSV Support

// Import the universal CSV mapper
let csvMapper = null;

function setupFileUpload() {
    console.log('Setting up file upload with universal CSV support...');
    
    const fileInput = document.getElementById('csvFiles');
    const uploadArea = document.getElementById('fileUploadArea');

    if (!fileInput || !uploadArea) {
        console.error('File upload elements not found');
        return;
    }
    
    // Prevent multiple setup
    if (uploadArea.hasAttribute('data-setup')) {
        console.log('File upload already set up');
        return;
    }
    
    uploadArea.setAttribute('data-setup', 'true');
    console.log('Setting up file upload handlers...');

    // Initialize CSV mapper
    if (typeof UniversalCSVMapper !== 'undefined') {
        csvMapper = new UniversalCSVMapper();
    }

    // Clear any existing event listeners by cloning the elements
    const newUploadArea = uploadArea.cloneNode(true);
    const newFileInput = fileInput.cloneNode(true);
    
    uploadArea.parentNode.replaceChild(newUploadArea, uploadArea);
    fileInput.parentNode.replaceChild(newFileInput, fileInput);

    // Get fresh references
    const freshUploadArea = document.getElementById('fileUploadArea');
    const freshFileInput = document.getElementById('csvFiles');

    // File input change handler
    freshFileInput.addEventListener('change', function(event) {
        console.log('File input changed, files:', event.target.files.length);
        const files = Array.from(event.target.files);
        if (files.length > 0) {
            addFiles(files);
        }
    });

    // Reliable click handler for upload area
    freshUploadArea.addEventListener('click', function(e) {
        e.preventDefault();
        e.stopPropagation();
        
        console.log('Upload area clicked, opening file dialog');
        openFileDialog();
    });
    
    // Drag and drop handlers
    freshUploadArea.addEventListener('dragover', function(e) {
        e.preventDefault();
        e.stopPropagation();
        freshUploadArea.classList.add('dragover');
        freshUploadArea.style.backgroundColor = '#e0f2fe';
        freshUploadArea.style.borderColor = '#0284c7';
    });
    
    freshUploadArea.addEventListener('dragleave', function(e) {
        e.preventDefault();
        e.stopPropagation();
        freshUploadArea.classList.remove('dragover');
        freshUploadArea.style.backgroundColor = '';
        freshUploadArea.style.borderColor = '';
    });
    
    freshUploadArea.addEventListener('drop', function(e) {
        e.preventDefault();
        e.stopPropagation();
        freshUploadArea.classList.remove('dragover');
        freshUploadArea.style.backgroundColor = '';
        freshUploadArea.style.borderColor = '';
        
        const files = Array.from(e.dataTransfer.files);
        console.log('Files dropped:', files.map(f => f.name));
        if (files.length > 0) {
            addFiles(files);
        }
    });
    
    console.log('File upload setup complete with universal CSV support');
}

// Reliable file dialog opener
function openFileDialog() {
    const input = document.createElement('input');
    input.type = 'file';
    input.multiple = true;
    input.accept = '.csv,.txt';
    input.style.display = 'none';
    
    input.addEventListener('change', function(e) {
        if (e.target.files.length > 0) {
            const files = Array.from(e.target.files);
            console.log('Files selected via dialog:', files.map(f => f.name));
            addFiles(files);
        }
        document.body.removeChild(input);
    });
    
    document.body.appendChild(input);
    input.click();
}

// Enhanced addFiles with universal CSV processing
async function addFiles(files) {
    console.log('Adding files with universal CSV processing:', files.map(f => f.name));
    
    if (!files || files.length === 0) {
        console.log('No files to add');
        return;
    }
    
    const processedFiles = [];
    
    for (const file of files) {
        const name = file.name.toLowerCase();
        const isCSV = name.endsWith('.csv') || name.endsWith('.txt');
        
        if (isCSV) {
            console.log(`Processing CSV file: ${file.name}`);
            
            try {
                // Convert CSV to standard format if mapper is available
                if (csvMapper && !file.name.includes('_converted')) {
                    const convertedFile = await convertCSVToStandardFormat(file);
                    processedFiles.push(convertedFile);
                } else {
                    processedFiles.push(file);
                }
            } catch (error) {
                console.warn(`CSV conversion failed for ${file.name}, using original:`, error);
                processedFiles.push(file);
            }
        } else {
            console.log(`Skipping non-CSV file: ${file.name}`);
        }
    }

    if (processedFiles.length === 0) {
        showMessage('Please select CSV files only. Found: ' + files.map(f => f.name).join(', '), 'error');
        return;
    }

    // Add processed files to selection (avoid duplicates by name)
    processedFiles.forEach(newFile => {
        const exists = selectedFiles.some(existingFile => existingFile.name === newFile.name);
        if (!exists) {
            selectedFiles.push(newFile);
            console.log(`Added file: ${newFile.name}`);
        } else {
            console.log(`File already exists: ${newFile.name}`);
        }
    });
    
    console.log('Total files now:', selectedFiles.length);
    
    updateFileDisplay();
    updateButtonStates();
    
    showMessage(`Added ${processedFiles.length} CSV file(s). Total: ${selectedFiles.length}`, 'success');
}

// Convert CSV to standard format using universal mapper
async function convertCSVToStandardFormat(file) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        
        reader.onload = function(e) {
            try {
                const content = e.target.result;
                const convertedContent = csvMapper.convertToStandardFormat(content, file.name);
                
                const blob = new Blob([convertedContent], { type: 'text/csv' });
                const convertedFile = new File([blob], file.name.replace(/\.csv$/i, '_converted.csv'), { 
                    type: 'text/csv' 
                });
                
                console.log(`✅ Converted ${file.name} -> ${convertedFile.name}`);
                resolve(convertedFile);
            } catch (error) {
                console.error(`❌ Conversion error for ${file.name}:`, error);
                reject(error);
            }
        };
        
        reader.onerror = () => reject(new Error('Failed to read file'));
        reader.readAsText(file);
    });
}

function removeFile(index) {
    console.log('Removing file at index:', index);
    if (index >= 0 && index < selectedFiles.length) {
        const removed = selectedFiles.splice(index, 1)[0];
        console.log(`Removed file: ${removed.name}`);
        updateFileDisplay();
        updateButtonStates();
        showMessage(`Removed ${removed.name}`, 'info');
    }
}

function clearAllFiles() {
    console.log('Clearing all files');
    selectedFiles = [];
    const fileInput = document.getElementById('csvFiles');
    if (fileInput) fileInput.value = '';
    updateFileDisplay();
    updateButtonStates();
    hideTransactionResults();
    showMessage('All files cleared', 'info');
}

function updateFileDisplay() {
    const selectedFilesDiv = document.getElementById('selectedFiles');
    const fileList = document.getElementById('fileList');
    const fileCount = document.getElementById('fileCount');
    
    if (!selectedFilesDiv || !fileList) {
        console.error('File display elements not found');
        return;
    }
    
    if (selectedFiles.length === 0) {
        selectedFilesDiv.style.display = 'none';
        return;
    }

    selectedFilesDiv.style.display = 'block';
    if (fileCount) fileCount.textContent = selectedFiles.length;
    
    fileList.innerHTML = selectedFiles.map((file, index) => `
        <div class="file-item">
            <div class="file-info">
                <div class="file-name">📄 ${escapeHtml(file.name)}</div>
                <div class="file-size">${formatFileSize(file.size)}</div>
            </div>
            <button class="file-remove" onclick="removeFile(${index})" title="Remove file">×</button>
        </div>
    `).join('');
}

function updateButtonStates() {
    const processBtn = document.getElementById('processBtn');
    const analyzeBtn = document.getElementById('analyzeBtn');
    
    if (!processBtn || !analyzeBtn) return;
    
    const hasFiles = selectedFiles.length > 0;
    
    processBtn.disabled = !hasFiles;
    analyzeBtn.disabled = !hasFiles;
    
    if (hasFiles) {
        processBtn.innerHTML = `🔄 Process ${selectedFiles.length} File(s)`;
        analyzeBtn.innerHTML = `📊 Analyze ${selectedFiles.length} File(s)`;
    } else {
        processBtn.innerHTML = '🔄 Process & Update Balances';
        analyzeBtn.innerHTML = '📊 Analyze Only (No Updates)';
    }
}

async function processTransactions() {
    console.log('processTransactions called with files:', selectedFiles.map(f => f.name));
    
    if (selectedFiles.length === 0) {
        showMessage('Please select CSV files first', 'error');
        return;
    }

    const processBtn = document.getElementById('processBtn');
    const originalText = processBtn.innerHTML;
    
    // Set loading state
    processBtn.disabled = true;
    processBtn.innerHTML = '🔄 Processing...';

    try {
        const formData = new FormData();
        
        // Add each file to form data
        selectedFiles.forEach((file, index) => {
            console.log(`Adding file ${index + 1}: ${file.name} (${file.size} bytes)`);
            formData.append('files', file);
        });
        
        // Add processing options
        const autoUpdate = document.getElementById('autoUpdateBalances');
        const updateCategories = document.getElementById('updateCategories');
        
        formData.append('auto_update', autoUpdate ? autoUpdate.checked.toString() : 'true');
        formData.append('update_categories', updateCategories ? updateCategories.checked.toString() : 'true');

        console.log('Uploading files to /api/upload-transactions...');

        const response = await fetch('/api/upload-transactions', {
            method: 'POST',
            body: formData
        });

        console.log('Response status:', response.status);

        if (!response.ok) {
            const errorText = await response.text();
            throw new Error(`HTTP ${response.status}: ${errorText}`);
        }

        const result = await response.json();
        console.log('Upload response:', result);
        
        if (result.success) {
            showTransactionResults({
                type: 'success',
                title: '✅ Processing Complete',
                message: result.message,
                details: [
                    `Files processed: ${result.files_processed}`,
                    'Card balances updated',
                    'Category spending updated'
                ]
            });
            
            // Clear files after successful processing
            clearAllFiles();
            
            // Refresh dashboard if it's active
            if (document.getElementById('dashboard-tab')?.classList.contains('active')) {
                setTimeout(() => {
                    if (typeof loadDashboard === 'function') {
                        loadDashboard();
                    }
                }, 1000);
            }
        } else {
            throw new Error(result.error || 'Processing failed');
        }
    } catch (err) {
        console.error('Error processing transactions:', err);
        showTransactionResults({
            type: 'error',
            title: '❌ Processing Failed',
            message: err.message,
            details: [
                'Check browser console for details',
                'Verify CSV file format is correct',
                'Ensure server is running'
            ]
        });
    } finally {
        // Restore button state
        processBtn.disabled = selectedFiles.length === 0;
        processBtn.innerHTML = selectedFiles.length > 0 ? 
            `🔄 Process ${selectedFiles.length} File(s)` : originalText;
    }
}

async function analyzeOnly() {
    console.log('analyzeOnly called with files:', selectedFiles.map(f => f.name));
    
    if (selectedFiles.length === 0) {
        showMessage('Please select CSV files first', 'error');
        return;
    }

    const analyzeBtn = document.getElementById('analyzeBtn');
    const originalText = analyzeBtn.innerHTML;
    
    // Set loading state
    analyzeBtn.disabled = true;
    analyzeBtn.innerHTML = '📊 Analyzing...';

    try {
        const formData = new FormData();
        
        // Add each file to form data
        selectedFiles.forEach(file => {
            formData.append('files', file);
        });
        
        // Set to analyze only (no balance updates)
        formData.append('auto_update', 'false');
        formData.append('update_categories', document.getElementById('updateCategories')?.checked.toString() || 'true');

        console.log('Uploading files for analysis...');

        const response = await fetch('/api/upload-transactions', {
            method: 'POST',
            body: formData
        });

        if (!response.ok) {
            const errorText = await response.text();
            throw new Error(`HTTP ${response.status}: ${errorText}`);
        }

        const result = await response.json();
        console.log('Analysis response:', result);
        
        if (result.success) {
            showTransactionResults({
                type: 'info',
                title: '📊 Analysis Complete',
                message: result.message,
                details: [
                    `Files analyzed: ${result.files_processed}`,
                    'No balances were updated',
                    'Category spending updated for reference'
                ]
            });
        } else {
            throw new Error(result.error || 'Analysis failed');
        }
    } catch (err) {
        console.error('Error analyzing transactions:', err);
        showTransactionResults({
            type: 'error',
            title: '❌ Analysis Failed',
            message: err.message,
            details: [
                'Check browser console for details',
                'Verify CSV file format is correct'
            ]
        });
    } finally {
        // Restore button state
        analyzeBtn.disabled = selectedFiles.length === 0;
        analyzeBtn.innerHTML = selectedFiles.length > 0 ? 
            `📊 Analyze ${selectedFiles.length} File(s)` : originalText;
    }
}

// Helper function to show transaction results
function showTransactionResults(config) {
    const resultsDiv = document.getElementById('transactionResults');
    if (!resultsDiv) return;
    
    resultsDiv.innerHTML = `
        <div class="results-card ${config.type}">
            <h4>${config.title}</h4>
            <p>${config.message}</p>
            ${config.details ? `
                <ul style="margin-top: 1rem; margin-left: 1rem;">
                    ${config.details.map(detail => `<li>${detail}</li>`).join('')}
                </ul>
            ` : ''}
        </div>
    `;
    
    resultsDiv.style.display = 'block';
    resultsDiv.scrollIntoView({ behavior: 'smooth' });
}

function hideTransactionResults() {
    const resultsDiv = document.getElementById('transactionResults');
    if (resultsDiv) {
        resultsDiv.style.display = 'none';
    }
}

// Initialize when transactions tab is shown
function initializeTransactionsTab() {
    console.log('Initializing transactions tab...');
    
    // Small delay to ensure DOM is ready
    setTimeout(() => {
        setupFileUpload();
        updateButtonStates();
    }, 100);
}

// Auto-initialize when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    // Initialize if transactions tab is already active
    if (document.getElementById('transactions-tab')?.classList.contains('active')) {
        initializeTransactionsTab();
    }
});

// Export functions for use in other modules
if (typeof window !== 'undefined') {
    window.setupFileUpload = setupFileUpload;
    window.initializeTransactionsTab = initializeTransactionsTab;
    window.addFiles = addFiles;
    window.removeFile = removeFile;
    window.clearAllFiles = clearAllFiles;
    window.processTransactions = processTransactions;
    window.analyzeOnly = analyzeOnly;
}