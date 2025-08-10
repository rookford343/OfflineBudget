// Transaction Import Functions

function setupFileUpload() {
    const fileInput = document.getElementById('csvFiles');
    const uploadArea = document.getElementById('fileUploadArea');

    if (!fileInput || !uploadArea) {
        console.log('File upload elements not found');
        return;
    }
    
    if (uploadArea.hasAttribute('data-setup')) {
        console.log('File upload already set up');
        return;
    }
    
    uploadArea.setAttribute('data-setup', 'true');
    console.log('Setting up file upload...');

    // Simple file input change handler
    fileInput.onchange = function(event) {
        console.log('File input changed');
        const files = Array.from(event.target.files);
        console.log('Selected files:', files.map(f => f.name));
        addFiles(files);
    };

    // Simple click handler - remove the complex event prevention
    uploadArea.onclick = function(e) {
        if (e.target !== fileInput) {
            console.log('Upload area clicked');
            fileInput.click();
        }
    };
    
    // Simple drag and drop
    uploadArea.ondragover = function(e) {
        e.preventDefault();
        uploadArea.classList.add('dragover');
    };
    
    uploadArea.ondragleave = function(e) {
        e.preventDefault();
        uploadArea.classList.remove('dragover');
    };
    
    uploadArea.ondrop = function(e) {
        e.preventDefault();
        uploadArea.classList.remove('dragover');
        const files = Array.from(e.dataTransfer.files);
        console.log('Files dropped:', files.map(f => f.name));
        addFiles(files);
    };
    
    console.log('File upload setup complete');
}

function addFiles(files) {
    console.log('Adding files:', files.map(f => f.name));
    
    if (!files || files.length === 0) {
        console.log('No files to add');
        return;
    }
    
    // Very simple CSV validation - just check the extension
    const csvFiles = files.filter(file => {
        const name = file.name.toLowerCase();
        const isCSV = name.endsWith('.csv');
        console.log(`File "${file.name}": is CSV = ${isCSV}`);
        return isCSV;
    });

    if (csvFiles.length === 0) {
        showMessage('No CSV files found. Please select files ending in .csv', 'error');
        console.log('Available files:', files.map(f => f.name));
        return;
    }

    // Add files without duplicate checking for now
    selectedFiles = selectedFiles.concat(csvFiles);
    console.log('Total files now:', selectedFiles.length);
    
    updateFileDisplay();
    updateButtonStates();
    
    showMessage(`Added ${csvFiles.length} file(s)`, 'success');
}

function removeFile(index) {
    selectedFiles.splice(index, 1);
    updateFileDisplay();
    updateButtonStates();
}

function clearAllFiles() {
    selectedFiles = [];
    const fileInput = document.getElementById('csvFiles');
    if (fileInput) fileInput.value = '';
    updateFileDisplay();
    updateButtonStates();
    hideTransactionResults();
}

function updateFileDisplay() {
    const selectedFilesDiv = document.getElementById('selectedFiles');
    const fileList = document.getElementById('fileList');
    const fileCount = document.getElementById('fileCount');
    
    if (!selectedFilesDiv || !fileList) {
        console.log('File display elements not found');
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
    setTransactionButtonLoading(processBtn, '🔄 Processing...');

    try {
        const formData = new FormData();
        
        selectedFiles.forEach((file, index) => {
            console.log(`Adding file ${index + 1}: ${file.name} (${file.size} bytes)`);
            formData.append('files', file);
        });
        
        const autoUpdate = document.getElementById('autoUpdateBalances');
        const updateCategories = document.getElementById('updateCategories');
        
        formData.append('auto_update', autoUpdate ? autoUpdate.checked : true);
        formData.append('update_categories', updateCategories ? updateCategories.checked : true);

        console.log('Uploading files...');

        const response = await fetch('/api/upload-transactions', {
            method: 'POST',
            body: formData
        });

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        const result = await response.json();
        console.log('Upload response:', result);
        
        if (result.success) {
            showTransactionResults({
                type: 'success',
                title: '✅ Processing Complete',
                message: result.message,
                details: [`Files processed: ${result.files_processed}`]
            });
            
            clearAllFiles();
            
            if (document.getElementById('dashboard-tab')?.classList.contains('active')) {
                setTimeout(loadDashboard, 1000);
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
            details: ['Check browser console for details']
        });
    } finally {
        restoreTransactionButton(processBtn, selectedFiles.length > 0 ? 
            `🔄 Process ${selectedFiles.length} File(s)` : '🔄 Process & Update Balances');
    }
}

async function analyzeOnly() {
    if (selectedFiles.length === 0) {
        showMessage('Please select CSV files first', 'error');
        return;
    }

    const analyzeBtn = document.getElementById('analyzeBtn');
    setTransactionButtonLoading(analyzeBtn, '📊 Analyzing...');

    try {
        const formData = new FormData();
        
        selectedFiles.forEach(file => {
            formData.append('files', file);
        });
        
        formData.append('auto_update', 'false');
        formData.append('update_categories', document.getElementById('updateCategories')?.checked || true);

        const response = await fetch('/api/upload-transactions', {
            method: 'POST',
            body: formData
        });

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        const result = await response.json();
        
        if (result.success) {
            showTransactionResults({
                type: 'info',
                title: '📊 Analysis Complete',
                message: result.message,
                details: [`Files analyzed: ${result.files_processed}`, 'No balances updated']
            });
        } else {
            throw new Error(result.error || 'Analysis failed');
        }
    } catch (err) {
        console.error('Error analyzing transactions:', err);
        showTransactionResults({
            type: 'error',
            title: '❌ Analysis Failed',
            message: err.message
        });
    } finally {
        restoreTransactionButton(analyzeBtn, selectedFiles.length > 0 ? 
            `📊 Analyze ${selectedFiles.length} File(s)` : '📊 Analyze Only (No Updates)');
    }
}

// Legacy helper functions for compatibility
function handleDragOver(event) {
    event.preventDefault();
    event.stopPropagation();
    event.currentTarget.classList.add('dragover');
}

function handleDragLeave(event) {
    event.preventDefault();
    event.stopPropagation();
    event.currentTarget.classList.remove('dragover');
}

function handleDrop(event) {
    event.preventDefault();
    event.stopPropagation();
    event.currentTarget.classList.remove('dragover');
    
    const files = Array.from(event.dataTransfer.files);
    console.log('Dropped files:', files.map(f => f.name));
    
    if (files.length > 0) {
        addFiles(files);
    }
}

function handleFileSelect(event) {
    console.log('File selection event triggered');
    const files = Array.from(event.target.files);
    console.log('Selected files:', files.map(f => f.name));
    
    if (files.length > 0) {
        addFiles(files);
    }
}

function updateSelectedFiles() {
    const selectedFilesDiv = document.getElementById('selectedFiles');
    const processBtn = document.getElementById('processBtn');
    const analyzeBtn = document.getElementById('analyzeBtn');
    
    if (selectedFiles.length === 0) {
        selectedFilesDiv.innerHTML = '';
        processBtn.disabled = true;
        analyzeBtn.disabled = true;
        return;
    }

    selectedFilesDiv.innerHTML = `
        <div class="card" style="margin-top: 1rem;">
            <h4>Selected Files (${selectedFiles.length})</h4>
            ${selectedFiles.map(file => `
                <div class="item-details">📄 ${file.name} (${(file.size / 1024).toFixed(1)} KB)</div>
            `).join('')}
        </div>
    `;
    
    processBtn.disabled = false;
    analyzeBtn.disabled = false;
}