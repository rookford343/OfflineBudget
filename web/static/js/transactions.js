// Transaction Import Functions with Universal CSV Support and Current Month Filtering

// Import the universal CSV mapper
let csvMapper = null;

// Global variable to store processed files for analysis
window.lastProcessedFiles = [];

// NEW: Store files for later analysis use
async function storeFilesForAnalysis(files) {
    window.lastProcessedFiles = [];
    
    for (let file of files) {
        try {
            const content = await file.text();
            window.lastProcessedFiles.push({
                name: file.name,
                content: content,
                size: file.size,
                type: file.type
            });
        } catch (err) {
            console.warn('Could not store file for analysis:', file.name, err);
        }
    }
    
    console.log(`📁 Stored ${window.lastProcessedFiles.length} files for analysis`);
}

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
    console.log('Adding files:', files.map(f => f.name));
    
    if (!files || files.length === 0) {
        console.log('No files to add');
        return;
    }
    
    const processedFiles = [];
    
    for (const file of files) {
        const name = file.name.toLowerCase();
        
        if (name.endsWith('.csv') || name.endsWith('.txt')) {
            console.log(`Processing CSV file: ${file.name}`);
            
            try {
                // Check if conversion is needed
                const needsConv = await needsConversion(file);
                
                if (needsConv) {
                    console.log(`Converting ${file.name}...`);
                    const convertedFile = await convertCSVToStandardFormat(file);
                    processedFiles.push(convertedFile);
                    console.log(`✅ Converted ${file.name} to standard format`);
                } else {
                    console.log(`✅ ${file.name} already in standard format`);
                    processedFiles.push(file);
                }
            } catch (error) {
                console.warn(`Conversion failed for ${file.name}, using original:`, error);
                processedFiles.push(file);
            }
        } else {
            console.log(`Skipping non-CSV file: ${file.name}`);
        }
    }
    
    if (processedFiles.length === 0) {
        showMessage('No valid CSV files found', 'error');
        return;
    }
    
    // Add files to selection
    processedFiles.forEach(newFile => {
        const exists = selectedFiles.some(existingFile => existingFile.name === newFile.name);
        if (!exists) {
            selectedFiles.push(newFile);
            console.log(`Added to queue: ${newFile.name}`);
        }
    });
    
    updateFileDisplay();
    updateButtonStates();
    
    showMessage(`Added ${processedFiles.length} CSV file(s). Ready to process!`, 'success');
}

// NEW: Check if file needs conversion by peeking at headers
async function needsConversion(file) {
    return new Promise((resolve) => {
        try {
            const reader = new FileReader();
            
            reader.onload = function(e) {
                try {
                    const content = e.target.result;
                    const firstLine = content.split('\n')[0];
                    const headers = parseCSVRow(firstLine);
                    
                    const formatType = detectCSVFormat(headers);
                    
                    // Only Chase format doesn't need conversion
                    resolve(formatType !== 'chase');
                    
                } catch (error) {
                    console.warn('Error checking file headers:', error);
                    resolve(true); // Assume needs conversion if can't determine
                }
            };
            
            reader.onerror = () => {
                console.warn('Error reading file for header check');
                resolve(true);
            };
            
            reader.readAsText(file.slice(0, 1024));
        } catch (error) {
            console.warn('Error in needsConversion:', error);
            resolve(true);
        }
    });
}

// Convert CSV to standard format using universal mapper
async function convertCSVToStandardFormat(file) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        
        reader.onload = function(e) {
            try {
                const content = e.target.result;
                const lines = content.trim().split('\n');
                
                if (lines.length < 2) {
                    throw new Error('CSV must have header and data');
                }
                
                const headers = parseCSVRow(lines[0]);
                console.log('Original headers:', headers);
                
                // Detect format type
                const formatType = detectCSVFormat(headers);
                console.log(`Detected format: ${formatType}`);
                
                let convertedContent;
                
                switch(formatType) {
                    case 'chase':
                        // Already in correct format
                        console.log('Chase format detected - no conversion needed');
                        resolve(file);
                        return;
                        
                    case 'citi':
                        convertedContent = convertCitiFormat(lines, headers);
                        break;
                        
                    case 'generic':
                        convertedContent = convertGenericFormat(lines, headers);
                        break;
                        
                    default:
                        console.warn('Unknown format, attempting generic conversion');
                        convertedContent = convertGenericFormat(lines, headers);
                }
                
                console.log('Conversion complete');
                
                const blob = new Blob([convertedContent], { type: 'text/csv' });
                const convertedFile = new File(
                    [blob], 
                    file.name.replace(/\.csv$/i, '_converted.csv'), 
                    { type: 'text/csv' }
                );
                
                resolve(convertedFile);
                
            } catch (error) {
                console.error(`Conversion error: ${error.message}`);
                // Return original file if conversion fails
                resolve(file);
            }
        };
        
        reader.onerror = () => {
            console.error('Failed to read file');
            resolve(file);
        };
        
        reader.readAsText(file);
    });
}

// Detect CSV format based on headers
function detectCSVFormat(headers) {
    const headerLower = headers.map(h => h.toLowerCase().trim());
    
    // Check for Chase format (already standard)
    if (headerLower.includes('transaction date') && 
        headerLower.includes('post date') && 
        headerLower.includes('amount')) {
        return 'chase';
    }
    
    // Check for Citi format
    if ((headerLower.includes('date') || headerLower.some(h => h === 'date')) && 
        headerLower.includes('debit') && 
        headerLower.includes('credit')) {
        return 'citi';
    }
    
    // Check for Bank of America format
    if (headerLower.includes('posted date') && 
        headerLower.includes('payee') && 
        headerLower.includes('amount')) {
        return 'bofa';
    }
    
    return 'generic';
}

// Convert Citi format to standard format
function convertCitiFormat(lines, headers) {
    console.log('Converting Citi format...');
    
    // Find column indices
    const dateCol = headers.findIndex(h => h.toLowerCase().trim() === 'date');
    const descCol = headers.findIndex(h => h.toLowerCase().includes('description'));
    const debitCol = headers.findIndex(h => h.toLowerCase().includes('debit'));
    const creditCol = headers.findIndex(h => h.toLowerCase().includes('credit'));
    const categoryCol = headers.findIndex(h => h.toLowerCase().includes('category'));
    
    console.log('Citi column mapping:', {
        date: dateCol,
        description: descCol,
        debit: debitCol,
        credit: creditCol,
        category: categoryCol
    });
    
    // Create standard header
    const standardHeader = 'Transaction Date,Post Date,Description,Category,Type,Amount,Memo';
    const convertedLines = [standardHeader];
    
    // Process data rows
    for (let i = 1; i < lines.length; i++) {
        const line = lines[i].trim();
        if (!line) continue;
        
        const columns = parseCSVRow(line);
        if (columns.length < headers.length - 1) continue;
        
        // Extract data
        const date = dateCol !== -1 ? columns[dateCol] : '';
        const description = descCol !== -1 ? columns[descCol] : '';
        const debit = debitCol !== -1 ? columns[debitCol] : '';
        const credit = creditCol !== -1 ? columns[creditCol] : '';
        const category = categoryCol !== -1 ? columns[categoryCol] : '';
        
        // Convert amount: negative for debits (spending), positive for credits (payments)
        let amount = '0';
        let type = 'Sale';
        
        if (debit && debit.trim() !== '') {
            // Remove any currency symbols and convert to negative
            amount = '-' + debit.replace(/[$,]/g, '').trim();
            type = 'Sale';
        } else if (credit && credit.trim() !== '') {
            // Credits are positive (payments)
            amount = credit.replace(/[$,]/g, '').trim();
            type = 'Payment';
        }
        
        // Skip rows with no amount
        if (amount === '0' || amount === '-' || amount === '') {
            continue;
        }
        
        // Build standard row
        const standardRow = [
            escapeCSVField(date),           // Transaction Date
            escapeCSVField(date),           // Post Date (use same date)
            escapeCSVField(description),    // Description
            escapeCSVField(category),       // Category
            escapeCSVField(type),           // Type
            escapeCSVField(amount),         // Amount
            escapeCSVField('')              // Memo
        ].join(',');
        
        convertedLines.push(standardRow);
    }
    
    const result = convertedLines.join('\n');
    console.log(`Converted ${convertedLines.length - 1} Citi transactions`);
    
    // Log sample for debugging
    if (convertedLines.length > 1) {
        console.log('Sample converted row:', convertedLines[1]);
    }
    
    return result;
}

// Generic converter for unknown formats
function convertGenericFormat(lines, headers) {
    console.log('Converting generic format...');
    
    const headerLower = headers.map(h => h.toLowerCase());
    
    // Find best matches for required columns
    const dateCol = headerLower.findIndex(h => 
        h.includes('date') || h.includes('posted') || h.includes('trans'));
    const descCol = headerLower.findIndex(h => 
        h.includes('description') || h.includes('merchant') || h.includes('payee'));
    const amountCol = headerLower.findIndex(h => 
        h.includes('amount') || h.includes('debit') || h.includes('charge'));
    const categoryCol = headerLower.findIndex(h => 
        h.includes('category') || h.includes('type'));
    
    const standardHeader = 'Transaction Date,Post Date,Description,Category,Type,Amount,Memo';
    const convertedLines = [standardHeader];
    
    for (let i = 1; i < lines.length; i++) {
        const line = lines[i].trim();
        if (!line) continue;
        
        const columns = parseCSVRow(line);
        
        const date = dateCol !== -1 ? columns[dateCol] || '' : '';
        const description = descCol !== -1 ? columns[descCol] || '' : `Transaction ${i}`;
        const amount = amountCol !== -1 ? columns[amountCol] || '0' : '0';
        const category = categoryCol !== -1 ? columns[categoryCol] || '' : '';
        
        const standardRow = [
            escapeCSVField(date),
            escapeCSVField(date),
            escapeCSVField(description),
            escapeCSVField(category),
            escapeCSVField('Sale'),
            escapeCSVField(amount),
            escapeCSVField('')
        ].join(',');
        
        convertedLines.push(standardRow);
    }
    
    return convertedLines.join('\n');
}

// NEW: Comprehensive CSV analysis before processing
async function analyzeCSVBeforeProcessing(files) {
    console.log('🔍 Analyzing CSV files before processing...');
    
    const analysisResults = [];
    
    for (const file of files) {
        try {
            const content = await readFileAsText(file);
            const lines = content.trim().split('\n');
            
            if (lines.length < 2) continue;
            
            const headers = parseCSVRow(lines[0]);
            const sampleRows = lines.slice(1, Math.min(6, lines.length))
                .map(line => parseCSVRow(line));
            
            // Analyze structure
            const analysis = {
                filename: file.name,
                totalRows: lines.length - 1,
                headers: headers,
                columnCount: headers.length,
                sampleData: sampleRows,
                descriptionColumn: findDescriptionColumn(headers),
                amountColumn: findAmountColumn(headers),
                dateColumn: findDateColumn(headers),
                categoryColumn: findCategoryColumn(headers)
            };
            
            // Extract sample descriptions for preview
            if (analysis.descriptionColumn !== -1) {
                analysis.sampleDescriptions = sampleRows
                    .map(row => row[analysis.descriptionColumn])
                    .filter(desc => desc && desc.trim())
                    .slice(0, 5);
            }
            
            analysisResults.push(analysis);
            
        } catch (error) {
            console.error(`Error analyzing ${file.name}:`, error);
        }
    }
    
    return analysisResults;
}

// NEW: Smart column detection
function findDescriptionColumn(headers) {
    const descriptionPatterns = [
        'description', 'merchant', 'payee', 'desc', 'transaction',
        'vendor', 'details', 'memo'
    ];
    
    for (let i = 0; i < headers.length; i++) {
        const header = headers[i].toLowerCase();
        for (const pattern of descriptionPatterns) {
            if (header.includes(pattern)) {
                console.log(`📝 Found description column: "${headers[i]}" at index ${i}`);
                return i;
            }
        }
    }
    return -1;
}

function findAmountColumn(headers) {
    for (let i = 0; i < headers.length; i++) {
        const header = headers[i].toLowerCase();
        if (header === 'amount' || (header.includes('amount') && !header.includes('original'))) {
            return i;
        }
    }
    return -1;
}

function findDateColumn(headers) {
    for (let i = 0; i < headers.length; i++) {
        const header = headers[i].toLowerCase();
        if (header.includes('date') && header.includes('transaction')) {
            return i;
        }
    }
    return -1;
}

function findCategoryColumn(headers) {
    for (let i = 0; i < headers.length; i++) {
        const header = headers[i].toLowerCase();
        if (header === 'category' || header === 'cat') {
            return i;
        }
    }
    return -1;
}

// NEW: Pre-processing validation and smart conversion
async function smartCSVProcessing(files) {
    console.log('🧠 Starting smart CSV processing...');
    
    // First, analyze all files
    const analyses = await analyzeCSVBeforeProcessing(files);
    
    // Show analysis results to user
    showCSVAnalysisResults(analyses);
    
    // Process each file with smart conversion
    const processedFiles = [];
    
    for (let i = 0; i < files.length; i++) {
        const file = files[i];
        const analysis = analyses[i];
        
        if (!analysis) {
            console.warn(`⚠️ Skipping ${file.name} - analysis failed`);
            continue;
        }
        
        try {
            // Determine if conversion is needed
            const needsConversion = !hasStandardFormat(analysis);
            
            if (needsConversion) {
                console.log(`🔄 Converting ${file.name}...`);
                const convertedFile = await smartConvertCSV(file, analysis);
                
                // Validate conversion
                const validation = await validateConversion(file, convertedFile, analysis);
                if (validation.success) {
                    processedFiles.push(convertedFile);
                    console.log(`✅ Successfully converted ${file.name}`);
                } else {
                    console.warn(`⚠️ Conversion issues for ${file.name}, using original`);
                    processedFiles.push(file);
                }
            } else {
                console.log(`✅ ${file.name} already in standard format`);
                processedFiles.push(file);
            }
            
        } catch (error) {
            console.error(`❌ Error processing ${file.name}:`, error);
            processedFiles.push(file); // Fallback to original
        }
    }
    
    return processedFiles;
}

// NEW: Show CSV analysis results to user
function showCSVAnalysisResults(analyses) {
    const debugDiv = document.getElementById('debugResults');
    const debugContent = document.getElementById('debugContent');
    
    if (!debugDiv || !debugContent) return;
    
    let analysisHtml = `
        <h4>📊 CSV File Analysis</h4>
        <div style="margin-bottom: 1rem;">
            Found ${analyses.length} CSV file(s) for processing:
        </div>
    `;
    
    analyses.forEach((analysis, index) => {
        const hasGoodDescription = analysis.descriptionColumn !== -1 && 
            analysis.sampleDescriptions && 
            analysis.sampleDescriptions.length > 0;
        
        const qualityStatus = hasGoodDescription ? '✅ Good' : '⚠️ Needs Attention';
        const qualityColor = hasGoodDescription ? '#16a34a' : '#f59e0b';
        
        analysisHtml += `
            <div style="border: 1px solid #e5e7eb; border-radius: 8px; padding: 1rem; margin-bottom: 1rem; background: #f9fafb;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem;">
                    <h5 style="margin: 0; color: #374151;">${analysis.filename}</h5>
                    <span style="color: ${qualityColor}; font-weight: bold;">${qualityStatus}</span>
                </div>
                
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; font-size: 0.9rem;">
                    <div>
                        <strong>Structure:</strong><br>
                        • Rows: ${analysis.totalRows}<br>
                        • Columns: ${analysis.columnCount}<br>
                        • Headers: ${analysis.headers.slice(0, 3).join(', ')}${analysis.headers.length > 3 ? '...' : ''}
                    </div>
                    <div>
                        <strong>Key Columns:</strong><br>
                        • Description: ${analysis.descriptionColumn !== -1 ? `✅ Column ${analysis.descriptionColumn}` : '❌ Not found'}<br>
                        • Amount: ${analysis.amountColumn !== -1 ? `✅ Column ${analysis.amountColumn}` : '❌ Not found'}<br>
                        • Date: ${analysis.dateColumn !== -1 ? `✅ Column ${analysis.dateColumn}` : '❌ Not found'}
                    </div>
                </div>
                
                ${analysis.sampleDescriptions && analysis.sampleDescriptions.length > 0 ? `
                    <div style="margin-top: 1rem;">
                        <strong>Sample Descriptions:</strong>
                        <div style="background: white; padding: 0.5rem; border-radius: 4px; font-family: monospace; font-size: 0.8rem;">
                            ${analysis.sampleDescriptions.map(desc => `• ${escapeHtml(desc)}`).join('<br>')}
                        </div>
                    </div>
                ` : `
                    <div style="margin-top: 1rem; padding: 0.5rem; background: #fef3c7; border-radius: 4px; border-left: 4px solid #f59e0b;">
                        <strong>⚠️ Warning:</strong> No merchant descriptions found. This may result in poor categorization.
                    </div>
                `}
            </div>
        `;
    });
    
    debugContent.innerHTML = analysisHtml;
    debugDiv.style.display = 'block';
}

// NEW: Smart CSV conversion using analysis
async function smartConvertCSV(file, analysis) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        
        reader.onload = function(e) {
            try {
                const content = e.target.result;
                const lines = content.trim().split('\n');
                
                // Use analysis to guide conversion
                const convertedContent = convertWithAnalysis(lines, analysis);
                
                const blob = new Blob([convertedContent], { type: 'text/csv' });
                const convertedFile = new File([blob], 
                    file.name.replace(/\.csv$/i, '_smart_converted.csv'), 
                    { type: 'text/csv' }
                );
                
                resolve(convertedFile);
            } catch (error) {
                reject(error);
            }
        };
        
        reader.onerror = () => reject(new Error('Failed to read file'));
        reader.readAsText(file);
    });
}

// NEW: Conversion using analysis data
function convertWithAnalysis(lines, analysis) {
    const standardHeader = 'Transaction Date,Post Date,Description,Category,Type,Amount,Memo';
    const convertedLines = [standardHeader];
    
    for (let i = 1; i < lines.length; i++) {
        const line = lines[i].trim();
        if (!line) continue;
        
        const columns = parseCSVRow(line);
        if (columns.length < analysis.columnCount - 1) continue; // Allow some flexibility
        
        // Extract data using analysis
        const transactionDate = analysis.dateColumn !== -1 ? 
            columns[analysis.dateColumn] || '' : '';
        const postDate = transactionDate; // Use same date if no separate post date
        
        // CRITICAL: Preserve original description
        let description = analysis.descriptionColumn !== -1 ? 
            columns[analysis.descriptionColumn] || 'Unknown Transaction' : 'Unknown Transaction';
        
        // Clean description but preserve merchant info
        description = cleanDescriptionPreserveMerchant(description);
        
        const category = analysis.categoryColumn !== -1 ? 
            columns[analysis.categoryColumn] || '' : '';
        const amount = analysis.amountColumn !== -1 ? 
            columns[analysis.amountColumn] || '0' : '0';
        
        const standardRow = [
            escapeCSVField(transactionDate),
            escapeCSVField(postDate),
            escapeCSVField(description), // This is the key field for categorization!
            escapeCSVField(category),
            escapeCSVField('Sale'),
            escapeCSVField(amount),
            escapeCSVField('') // Memo
        ].join(',');
        
        convertedLines.push(standardRow);
    }
    
    return convertedLines.join('\n');
}

// NEW: Clean description while preserving merchant names
function cleanDescriptionPreserveMerchant(description) {
    if (!description || description.trim() === '') {
        return 'Unknown Transaction';
    }
    
    // Remove quotes and extra whitespace
    let cleaned = description.replace(/^["']+|["']+$/g, '').trim();
    
    // Don't over-clean - preserve the core merchant identifier
    // Only remove obvious noise like trailing numbers, reference codes
    cleaned = cleaned.replace(/\s+\d{10,}$/, ''); // Remove long reference numbers
    cleaned = cleaned.replace(/\s+#\d+$/, ''); // Remove store numbers at end only
    
    return cleaned || 'Unknown Transaction';
}

// NEW: Validate conversion quality
async function validateConversion(originalFile, convertedFile, analysis) {
    try {
        const convertedContent = await readFileAsText(convertedFile);
        const convertedLines = convertedContent.trim().split('\n');
        
        // Check if descriptions are preserved
        let preservedDescriptions = 0;
        let totalDescriptions = 0;
        
        for (let i = 1; i < Math.min(10, convertedLines.length); i++) {
            const columns = parseCSVRow(convertedLines[i]);
            if (columns.length >= 3) {
                totalDescriptions++;
                const description = columns[2]; // Description column in standard format
                if (description && 
                    description !== 'Unknown Transaction' && 
                    description.trim() !== '' &&
                    description.length > 5) {
                    preservedDescriptions++;
                }
            }
        }
        
        const preservationRate = totalDescriptions > 0 ? 
            (preservedDescriptions / totalDescriptions) : 0;
        
        return {
            success: preservationRate > 0.5, // At least 50% descriptions preserved
            preservationRate,
            preservedDescriptions,
            totalDescriptions,
            quality: preservationRate > 0.8 ? 'Excellent' : 
                    preservationRate > 0.5 ? 'Good' : 'Poor'
        };
        
    } catch (error) {
        return { success: false, error: error.message };
    }
}

// NEW: Check if file already has standard format
function hasStandardFormat(analysis) {
    const standardHeaders = ['transaction date', 'description', 'amount'];
    const lowerHeaders = analysis.headers.map(h => h.toLowerCase());
    
    return standardHeaders.every(required => 
        lowerHeaders.some(header => header.includes(required))
    );
}

// NEW: Enhanced categorization testing with real data
async function testCategorizationWithRealData() {
    console.log('🧪 Testing categorization with real transaction data...');
    
    if (selectedFiles.length === 0) {
        showMessage('Please select CSV files first to test categorization', 'warning');
        return;
    }
    
    try {
        // Analyze first file to get sample descriptions
        const firstFile = selectedFiles[0];
        const content = await readFileAsText(firstFile);
        const lines = content.trim().split('\n');
        
        if (lines.length < 2) {
            showMessage('CSV file appears to be empty or invalid', 'error');
            return;
        }
        
        const headers = parseCSVRow(lines[0]);
        const descColumn = findDescriptionColumn(headers);
        
        if (descColumn === -1) {
            showMessage('Could not find description column in CSV', 'error');
            return;
        }
        
        // Extract real descriptions from the file
        const realDescriptions = [];
        for (let i = 1; i < Math.min(21, lines.length); i++) {
            const columns = parseCSVRow(lines[i]);
            if (columns[descColumn] && columns[descColumn].trim()) {
                realDescriptions.push({
                    description: columns[descColumn].trim(),
                    originalCategory: columns.length > descColumn + 1 ? columns[descColumn + 1] : '',
                    memo: ''
                });
            }
        }
        
        if (realDescriptions.length === 0) {
            showMessage('No valid descriptions found in CSV file', 'error');
            return;
        }
        
        // Test categorization with real data
        await testCategorizationAPI(realDescriptions.slice(0, 15));
        
    } catch (error) {
        console.error('Error testing with real data:', error);
        showMessage(`Error testing categorization: ${error.message}`, 'error');
    }
}

// NEW: API call for categorization testing
async function testCategorizationAPI(transactions) {
    try {
        console.log('🔍 Testing categorization via API...');
        
        const response = await fetch('/api/test-categorization', {
            method: 'POST',
            headers: { 
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            },
            body: JSON.stringify({ transactions })
        });
        
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${await response.text()}`);
        }
        
        const result = await response.json();
        
        if (result.success && result.results) {
            showCategorizationTestResults(result.results);
        } else {
            throw new Error('API returned no results');
        }
        
    } catch (error) {
        console.error('Categorization test API error:', error);
        showMessage(`Categorization test failed: ${error.message}`, 'error');
    }
}

// NEW: Show categorization test results with analysis
function showCategorizationTestResults(results) {
    // Count categories
    const categoryCount = {};
    results.forEach(result => {
        const category = result.assigned_category;
        categoryCount[category] = (categoryCount[category] || 0) + 1;
    });
    
    const otherCount = categoryCount['Other'] || 0;
    const totalCount = results.length;
    const otherPercentage = ((otherCount / totalCount) * 100).toFixed(1);
    
    // Determine result quality
    let qualityMessage = '';
    let qualityColor = '';
    
    if (otherPercentage > 80) {
        qualityMessage = '❌ Poor categorization - most transactions going to "Other"';
        qualityColor = '#dc2626';
    } else if (otherPercentage > 50) {
        qualityMessage = '⚠️ Moderate categorization - many transactions in "Other"';
        qualityColor = '#f59e0b';
    } else {
        qualityMessage = '✅ Good categorization - transactions properly sorted';
        qualityColor = '#16a34a';
    }
    
    const testHtml = `
        <div style="margin-top: 1.5rem; padding: 1rem; background: #f8f9fa; border-radius: 8px; border-left: 4px solid ${qualityColor};">
            <h5 style="margin: 0 0 1rem 0; color: ${qualityColor};">🧪 Categorization Test Results</h5>
            
            <div style="margin-bottom: 1rem; padding: 0.75rem; background: white; border-radius: 4px; border: 1px solid #e5e7eb;">
                <div style="font-weight: bold; color: ${qualityColor};">${qualityMessage}</div>
                <div style="margin-top: 0.5rem; font-size: 0.9rem;">
                    Tested ${totalCount} transactions • ${otherCount} went to "Other" (${otherPercentage}%)
                </div>
            </div>
            
            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; margin-bottom: 1rem;">
                <div>
                    <strong>Category Distribution:</strong>
                    ${Object.entries(categoryCount).map(([category, count]) => 
                        `<div style="color: ${getCategoryColor(category)};">• ${category}: ${count}</div>`
                    ).join('')}
                </div>
                <div>
                    <strong>Top Problematic Transactions:</strong>
                    ${results.filter(r => r.assigned_category === 'Other').slice(0, 3).map(r => 
                        `<div style="font-size: 0.8rem; color: #6b7280;">• ${escapeHtml(r.input.description.substring(0, 30))}...</div>`
                    ).join('')}
                </div>
            </div>
            
            <details style="margin-top: 1rem;">
                <summary style="cursor: pointer; font-weight: bold;">📋 Full Test Results (Click to expand)</summary>
                <div style="margin-top: 0.5rem; max-height: 300px; overflow-y: auto;">
                    <div style="display: grid; grid-template-columns: 2fr 1fr 1fr; gap: 0.5rem; font-size: 0.8rem; font-weight: bold; border-bottom: 1px solid #e5e7eb; padding-bottom: 0.25rem; margin-bottom: 0.5rem;">
                        <div>Description</div>
                        <div>Original Category</div>
                        <div>Assigned Category</div>
                    </div>
                    ${results.map(result => `
                        <div style="display: grid; grid-template-columns: 2fr 1fr 1fr; gap: 0.5rem; font-size: 0.75rem; margin-bottom: 0.25rem; padding: 0.25rem; background: white; border-radius: 4px;">
                            <div style="overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="${escapeHtml(result.input.description)}">${escapeHtml(result.input.description)}</div>
                            <div style="color: #6b7280;">${escapeHtml(result.input.originalCategory || 'None')}</div>
                            <div style="color: ${getCategoryColor(result.assigned_category)}; font-weight: bold;">${result.assigned_category}</div>
                        </div>
                    `).join('')}
                </div>
            </details>
            
            <div style="margin-top: 1rem; text-align: center;">
                <button class="btn btn-secondary" onclick="this.parentElement.parentElement.remove()">Close Test Results</button>
                ${otherPercentage > 50 ? `
                    <button class="btn btn-warning" onclick="showCategorizationTips()" style="margin-left: 0.5rem;">💡 Get Tips</button>
                ` : ''}
            </div>
        </div>
    `;
    
    const resultsDiv = document.getElementById('transactionResults');
    if (resultsDiv) {
        resultsDiv.insertAdjacentHTML('beforeend', testHtml);
        resultsDiv.style.display = 'block';
        resultsDiv.scrollIntoView({ behavior: 'smooth' });
    }
}

// NEW: Show categorization improvement tips
function showCategorizationTips() {
    const tips = `
🔧 Categorization Improvement Tips:

📊 Based on your test results, many transactions are going to "Other". Here's how to fix this:

1. ✅ CHECK YOUR CSV FILE:
   • Make sure the "Description" column contains actual merchant names
   • If you see "Unknown Transaction" everywhere, the CSV conversion is removing data

2. 🔄 TRY DIFFERENT UPLOAD OPTIONS:
   • Uncheck "Current month only for budgets" and re-upload
   • Try uploading your original CSV without any modifications

3. 🎯 LOOK FOR THESE PATTERNS:
   • Good: "WHOLE FOODS MARKET #123", "STARBUCKS COFFEE"
   • Bad: "Unknown Transaction", "Sale", "Purchase"

4. 🛠️ IF CATEGORIZATION IS STILL POOR:
   • Your bank's CSV format might need special handling
   • The transaction descriptions might be in a different column
   • Contact support with a sample of your CSV structure

5. 📋 CURRENT KEYWORD COVERAGE:
   • Groceries: Whole Foods, Kroger, Safeway, Target (grocery), etc.
   • Food & Drinks: Starbucks, McDonald's, Chipotle, restaurants, etc.
   • Shopping: Amazon, Walmart, Target, Best Buy, etc.
   • Services: Netflix, Spotify, utilities, insurance, etc.
   • Entertainment: Movies, Uber, hotels, travel, etc.

Would you like to try uploading your CSV again with different settings?
    `;
    
    alert(tips);
}

// Helper function to parse CSV row with quoted field support
function parseCSVRow(row) {
    const result = [];
    let current = '';
    let inQuotes = false;
    let i = 0;
    
    while (i < row.length) {
        const char = row[i];
        
        if (char === '"') {
            if (inQuotes && i + 1 < row.length && row[i + 1] === '"') {
                // Escaped quote
                current += '"';
                i += 2;
            } else {
                // Start or end of quoted field
                inQuotes = !inQuotes;
                i++;
            }
        } else if (char === ',' && !inQuotes) {
            result.push(current);
            current = '';
            i++;
        } else {
            current += char;
            i++;
        }
    }
    
    result.push(current);
    return result.map(field => field.trim());
}

// Helper to read file as text
function readFileAsText(file) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = e => resolve(e.target.result);
        reader.onerror = reject;
        reader.readAsText(file);
    });
}

// NEW: CSV conversion validation
async function validateCSVConversion(originalFile, convertedFile) {
    console.log('🔍 Validating CSV conversion...');
    
    try {
        // Read both files and compare key metrics
        const originalContent = await readFileAsText(originalFile);
        const convertedContent = await readFileAsText(convertedFile);
        
        const originalLines = originalContent.trim().split('\n');
        const convertedLines = convertedContent.trim().split('\n');
        
        // Sample some converted descriptions
        const sampleDescriptions = [];
        for (let i = 1; i < Math.min(6, convertedLines.length); i++) {
            const columns = parseCSVRow(convertedLines[i]);
            if (columns.length >= 3) {
                sampleDescriptions.push(columns[2]); // Description column
            }
        }
        
        const unknownCount = sampleDescriptions.filter(desc => 
            desc === 'Unknown Transaction' || desc === '').length;
        
        const validationResult = {
            originalRows: originalLines.length - 1,
            convertedRows: convertedLines.length - 1,
            sampleDescriptions,
            unknownDescriptions: unknownCount,
            conversionQuality: unknownCount === 0 ? 'Good' : 
                              unknownCount < sampleDescriptions.length ? 'Partial' : 'Poor'
        };
        
        console.log('📊 Validation result:', validationResult);
        return validationResult;
        
    } catch (error) {
        console.error('❌ Validation failed:', error);
        return null;
    }
}

// Helper function to escape CSV fields
function escapeCSVField(field) {
    if (!field) return '';
    
    const stringField = String(field);
    if (stringField.includes(',') || stringField.includes('"') || stringField.includes('\n')) {
        return '"' + stringField.replace(/"/g, '""') + '"';
    }
    return stringField;
}

// NEW: Improved CSV parsing that preserves merchant descriptions
function enhancedCSVConversion(csvContent, filename) {
    console.log(`🔧 Enhanced CSV conversion for: ${filename}`);
    
    const lines = csvContent.trim().split('\n');
    if (lines.length < 2) {
        throw new Error('CSV file must have at least a header and one data row');
    }
    
    const headerLine = lines[0];
    const headers = parseCSVRow(headerLine).map(h => h.replace(/"/g, '').trim().toLowerCase());
    
    console.log('📋 Original headers:', headers);
    
    // Enhanced column detection with multiple fallbacks
    const columnMap = detectColumnMapping(headers);
    console.log('🗺️ Column mapping:', columnMap);
    
    // Validate we found essential columns
    if (columnMap.description === undefined && columnMap.merchant === undefined) {
        console.warn('⚠️ No description/merchant column found, will use generic descriptions');
    }
    
    // Create standard header
    const standardHeader = 'Transaction Date,Post Date,Description,Category,Type,Amount,Memo';
    const convertedLines = [standardHeader];
    
    let successfulConversions = 0;
    let preservedDescriptions = 0;
    
    // Process data rows with enhanced error handling
    for (let i = 1; i < lines.length; i++) {
        const line = lines[i].trim();
        if (!line) continue;
        
        try {
            // Parse CSV row with proper quote handling
            const columns = parseCSVRow(line);
            
            if (columns.length < headers.length - 2) { // Allow some flexibility
                console.warn(`⚠️ Row ${i} has fewer columns than expected, skipping`);
                continue;
            }
            
            // Extract and validate data
            const rowData = extractRowData(columns, columnMap, headers, i);
            
            if (rowData.description && rowData.description !== 'Unknown Transaction') {
                preservedDescriptions++;
            }
            
            // Create standard row with proper CSV escaping
            const standardRow = [
                escapeCSVField(rowData.transactionDate),
                escapeCSVField(rowData.postDate),
                escapeCSVField(rowData.description),
                escapeCSVField(rowData.category),
                escapeCSVField(rowData.type),
                escapeCSVField(rowData.amount),
                escapeCSVField(rowData.memo)
            ].join(',');
            
            convertedLines.push(standardRow);
            successfulConversions++;
            
        } catch (error) {
            console.warn(`⚠️ Error processing row ${i}:`, error.message);
            continue;
        }
    }
    
    const result = convertedLines.join('\n');
    
    console.log(`✅ Conversion complete:
    - Input rows: ${lines.length - 1}
    - Successful conversions: ${successfulConversions}
    - Preserved descriptions: ${preservedDescriptions}
    - Description preservation rate: ${((preservedDescriptions / successfulConversions) * 100).toFixed(1)}%`);
    
    if (preservedDescriptions === 0) {
        console.error('❌ NO DESCRIPTIONS PRESERVED! All will categorize as "Other"');
    }
    
    return result;
}

// NEW: Enhanced column detection with multiple patterns
function detectColumnMapping(headers) {
    const columnMap = {};
    
    headers.forEach((header, index) => {
        const h = header.toLowerCase();
        
        // Transaction Date - various patterns
        if ((h.includes('transaction') && h.includes('date')) || 
            h === 'date' || h === 'trans date' || h === 'tran date') {
            columnMap.transactionDate = index;
        }
        
        // Post Date
        else if (h.includes('post') && h.includes('date')) {
            columnMap.postDate = index;
        }
        
        // Description/Merchant - CRITICAL for categorization
        else if (h.includes('description') || h.includes('merchant') || 
                 h.includes('payee') || h === 'desc') {
            columnMap.description = index;
            console.log(`📝 Found description column: "${header}" at index ${index}`);
        }
        
        // Amount - avoid original amount columns
        else if (h === 'amount' || (h.includes('amount') && !h.includes('original'))) {
            columnMap.amount = index;
        }
        
        // Category
        else if (h === 'category' || h === 'cat') {
            columnMap.category = index;
        }
        
        // Type
        else if (h === 'type' || h === 'transaction type' || h === 'trans type') {
            columnMap.type = index;
        }
        
        // Memo/Notes
        else if (h.includes('memo') || h.includes('note') || h.includes('reference')) {
            columnMap.memo = index;
        }
    });
    
    return columnMap;
}

// NEW: Enhanced row data extraction with fallbacks
function extractRowData(columns, columnMap, headers, rowIndex) {
    // Transaction Date
    const transactionDate = safeGetColumn(columns, columnMap.transactionDate, '');
    
    // Post Date (fallback to transaction date)
    const postDate = safeGetColumn(columns, columnMap.postDate, transactionDate);
    
    // Description - MOST IMPORTANT for categorization
    let description = safeGetColumn(columns, columnMap.description, '');
    
    // If no description found, try to find it in other columns
    if (!description || description.trim() === '') {
        // Look for non-empty columns that might contain description
        for (let i = 0; i < columns.length; i++) {
            const value = columns[i]?.trim();
            if (value && value !== '' && 
                !isDateString(value) && 
                !isNumericString(value) &&
                !isCommonCategoryWord(value)) {
                description = value;
                console.log(`📝 Using fallback description from column ${i}: "${description}"`);
                break;
            }
        }
    }
    
    // Final fallback
    if (!description || description.trim() === '') {
        description = 'Unknown Transaction';
        console.warn(`⚠️ Row ${rowIndex}: No description found, using fallback`);
    }
    
    // Clean up description - remove extra quotes and whitespace
    description = description.replace(/^["']+|["']+$/g, '').trim();
    
    return {
        transactionDate,
        postDate,
        description,
        category: safeGetColumn(columns, columnMap.category, ''),
        type: safeGetColumn(columns, columnMap.type, 'Sale'),
        amount: safeGetColumn(columns, columnMap.amount, '0'),
        memo: safeGetColumn(columns, columnMap.memo, '')
    };
}

// Helper functions
function safeGetColumn(columns, index, defaultValue = '') {
    if (index === undefined || index >= columns.length) {
        return defaultValue;
    }
    const value = columns[index];
    return value !== undefined && value !== null ? String(value).trim() : defaultValue;
}

function findColumnByPatterns(headers, patterns) {
    for (let i = 0; i < headers.length; i++) {
        const header = headers[i].toLowerCase().trim();
        for (const pattern of patterns) {
            if (header.includes(pattern)) {
                console.log(`Found column: "${headers[i]}" matches pattern "${pattern}" at index ${i}`);
                return i;
            }
        }
    }
    return -1;
}

function isDateString(str) {
    // Simple date pattern detection
    return /\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4}|\d{4}[\/\-]\d{1,2}[\/\-]\d{1,2}/.test(str);
}

function isNumericString(str) {
    // Check if string is primarily numeric (amount, account number, etc.)
    return /^[\d\.\-\+\$\,\s]+$/.test(str) && str.replace(/[\D]/g, '').length > 2;
}

function isCommonCategoryWord(str) {
    const commonWords = ['sale', 'debit', 'credit', 'purchase', 'payment', 'fee', 'charge'];
    return commonWords.includes(str.toLowerCase());
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

// FIXED: Add quiet version of clearAllFiles that doesn't show message
function clearAllFilesQuietly() {
    console.log('Clearing all files quietly');
    selectedFiles = [];
    const fileInput = document.getElementById('csvFiles');
    if (fileInput) fileInput.value = '';
    updateFileDisplay();
    updateButtonStates();
    hideTransactionResults();
    // No message shown for quiet clear
}

// Original clearAllFiles for manual user action
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

// NEW: Persistent results that don't auto-clear
function showPersistentTransactionResults(config) {
    const resultsDiv = document.getElementById('transactionResults');
    if (!resultsDiv) return;
    
    let categorizationHtml = '';
    
    // Show categorization preview if available
    if (config.categorization_preview && Object.keys(config.categorization_preview).length > 0) {
        categorizationHtml = `
            <div style="margin-top: 1.5rem; padding: 1rem; background: #f8f9fa; border-radius: 8px; border-left: 4px solid #28a745;">
                <h5 style="margin: 0 0 1rem 0; color: #28a745;">📊 Categorization Preview</h5>
                ${Object.entries(config.categorization_preview).map(([filename, transactions]) => `
                    <div style="margin-bottom: 1rem;">
                        <h6 style="margin: 0 0 0.5rem 0; font-weight: bold;">${filename}</h6>
                        <div style="display: grid; grid-template-columns: 2fr 1fr 1fr 1fr; gap: 0.5rem; font-size: 0.85rem; margin-bottom: 0.5rem; font-weight: bold; border-bottom: 1px solid #dee2e6; padding-bottom: 0.25rem;">
                            <div>Description</div>
                            <div>Original Category</div>
                            <div>Assigned Category</div>
                            <div>Amount</div>
                        </div>
                        ${transactions.slice(0, 12).map(transaction => {
                            const categoryColor = getCategoryColor(transaction.assigned_category);
                            return `
                                <div style="display: grid; grid-template-columns: 2fr 1fr 1fr 1fr; gap: 0.5rem; font-size: 0.8rem; margin-bottom: 0.25rem; padding: 0.25rem; background: white; border-radius: 4px;">
                                    <div style="overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="${escapeHtml(transaction.description)}">${escapeHtml(transaction.description.substring(0, 40))}${transaction.description.length > 40 ? '...' : ''}</div>
                                    <div style="color: #6b7280;">${escapeHtml(transaction.original_category || 'None')}</div>
                                    <div style="color: ${categoryColor}; font-weight: bold;">${transaction.assigned_category}</div>
                                    <div style="text-align: right;">$${transaction.amount.toFixed(2)}</div>
                                </div>
                            `;
                        }).join('')}
                        ${transactions.length > 12 ? `<div style="text-align: center; color: #6b7280; font-style: italic; margin-top: 0.5rem;">... and ${transactions.length - 12} more transactions</div>` : ''}
                    </div>
                `).join('')}
                <div style="margin-top: 1rem; font-size: 0.85rem; color: #6b7280;">
                    💡 <strong>Tip:</strong> If most transactions show "Unknown Transaction", the CSV conversion may be removing merchant names. Try uploading the original CSV without conversion.
                </div>
            </div>
        `;
    }
    
    resultsDiv.innerHTML = `
        <div class="results-card ${config.type}" style="position: relative;">
            <div style="position: absolute; top: 10px; right: 10px;">
                <button class="btn btn-small btn-secondary" onclick="clearTransactionResults()" title="Clear results">
                    ✕ Clear
                </button>
            </div>
            
            <h4>${config.title}</h4>
            <p>${config.message}</p>
            ${config.details ? `
                <ul style="margin-top: 1rem; margin-left: 1rem;">
                    ${config.details.map(detail => `<li>${detail}</li>`).join('')}
                </ul>
            ` : ''}
            ${categorizationHtml}
            
            <div style="margin-top: 1.5rem; text-align: center; display: flex; gap: 0.5rem; justify-content: center; flex-wrap: wrap;">
                <button class="btn btn-info" onclick="debugTransactionProcessing()">
                    🔍 View Category Debug Info
                </button>
                <button class="btn btn-secondary" onclick="testCategorizationSample()">
                    🧪 Test Categorization
                </button>
                ${config.processingSuccess ? `
                    <button class="btn btn-success" onclick="finishProcessingAndClear()" style="background: #16a34a;">
                        ✅ Complete & Clear Files
                    </button>
                ` : ''}
                <button class="btn btn-warning" onclick="uploadOriginalCSV()">
                    📁 Try Original CSV
                </button>
                <button onclick="debugFileUpload()" class="btn btn-info">
                    🔍 Debug File
                </button>
                <button onclick="testDirectUpload()" class="btn btn-info">
                    🧪 Test Upload
                </button>
            </div>
            
            <div style="margin-top: 1rem; padding: 0.75rem; background: #fef3c7; border-radius: 4px; border-left: 4px solid #f59e0b; font-size: 0.9rem;">
                <strong>🔍 Troubleshooting:</strong><br>
                • If you see "Unknown Transaction" for all descriptions, click "Try Original CSV"<br>
                • Use the debug button to see exactly what's being categorized<br>
                • Results will stay visible until you clear them manually
            </div>
        </div>
    `;
    
    resultsDiv.style.display = 'block';
    resultsDiv.scrollIntoView({ behavior: 'smooth' });
}

// NEW: Function to clear transaction results
function clearTransactionResults() {
    const resultsDiv = document.getElementById('transactionResults');
    const debugDiv = document.getElementById('debugResults');
    
    if (resultsDiv) {
        resultsDiv.style.display = 'none';
        resultsDiv.innerHTML = '';
    }
    
    if (debugDiv) {
        debugDiv.style.display = 'none';
        debugDiv.innerHTML = '';
    }
    
    showMessage('Results cleared', 'info');
}

// NEW: Function to complete processing and clean up
function finishProcessingAndClear() {
    // Clear files
    clearAllFilesQuietly();
    
    // Clear results
    clearTransactionResults();
    
    // Refresh dashboard if active
    if (document.getElementById('dashboard-tab')?.classList.contains('active')) {
        setTimeout(() => {
            if (typeof loadDashboard === 'function') {
                loadDashboard();
            }
        }, 500);
    }
    
    showMessage('Processing completed! Files cleared and dashboard refreshed.', 'success');
}

// NEW: Function to suggest uploading original CSV
function uploadOriginalCSV() {
    const message = `
The CSV conversion may be removing merchant descriptions. Try this:

1. Clear current files
2. Upload your ORIGINAL CSV file (not the converted one)
3. Uncheck "Current month only for budgets" 
4. Process again

The system will try to preserve the original merchant names for better categorization.
    `;
    
    if (confirm(message + '\n\nClear current files and try again?')) {
        clearAllFiles();
        clearTransactionResults();
    }
}

// Add this debug function to help troubleshoot upload issues
async function debugFileUpload() {
    console.log('🔍 DEBUG: File Upload Status');
    console.log('Selected files:', selectedFiles);
    
    if (selectedFiles.length === 0) {
        console.log('❌ No files selected');
        return;
    }
    
    // Check first file
    const file = selectedFiles[0];
    console.log('First file details:');
    console.log('  Name:', file.name);
    console.log('  Size:', file.size, 'bytes');
    console.log('  Type:', file.type || 'not specified');
    console.log('  Last Modified:', new Date(file.lastModified));
    
    // Try to read first few lines
    const reader = new FileReader();
    reader.onload = function(e) {
        const content = e.target.result;
        const lines = content.split('\n').slice(0, 5);
        console.log('First 5 lines of file:');
        lines.forEach((line, i) => {
            console.log(`  Line ${i}: ${line.substring(0, 100)}${line.length > 100 ? '...' : ''}`);
        });
        
        // Check for BOM or encoding issues
        const hasBOM = content.charCodeAt(0) === 0xFEFF;
        console.log('Has BOM:', hasBOM);
        
        // Parse first line as CSV
        const firstLine = lines[0];
        const headers = parseCSVRow(firstLine);
        console.log('Parsed headers:', headers);
        
        // Check if headers match expected format
        const expectedHeaders = ['Transaction Date', 'Post Date', 'Description', 'Category', 'Type', 'Amount', 'Memo'];
        const hasExpectedHeaders = expectedHeaders.every(h => 
            headers.some(header => header.toLowerCase().includes(h.toLowerCase()))
        );
        console.log('Has expected headers:', hasExpectedHeaders);
    };
    
    reader.onerror = function() {
        console.error('❌ Failed to read file');
    };
    
    reader.readAsText(file.slice(0, 10000)); // Read first 10KB
}

// Also add a manual test upload function
async function testDirectUpload() {
    if (selectedFiles.length === 0) {
        console.log('❌ No files to test');
        return;
    }
    
    console.log('🧪 Testing direct upload...');
    
    const formData = new FormData();
    formData.append('files', selectedFiles[0]);
    formData.append('auto_update', 'false');
    formData.append('update_categories', 'true');
    formData.append('current_month_only', 'false');
    
    try {
        const response = await fetch('/api/upload-transactions', {
            method: 'POST',
            body: formData
        });
        
        console.log('Response status:', response.status);
        const text = await response.text();
        console.log('Response text:', text);
        
        try {
            const json = JSON.parse(text);
            console.log('Parsed response:', json);
        } catch (e) {
            console.error('Failed to parse as JSON');
        }
    } catch (error) {
        console.error('Upload test failed:', error);
    }
}

// Helper function to show categorization preview
function showCategorizationPreview(preview) {
    const resultsDiv = document.getElementById('transactionResults');
    if (!resultsDiv || !preview) return;
    
    let html = '<div class="card" style="margin-top: 1rem;">';
    html += '<h4>📊 Categorization Preview</h4>';
    
    for (const [filename, transactions] of Object.entries(preview)) {
        html += `<h5>${filename}</h5>`;
        html += '<div style="max-height: 200px; overflow-y: auto;">';
        
        transactions.slice(0, 10).forEach(t => {
            const icon = t.assigned_category !== 'Other' ? '✅' : '❌';
            html += `<div>${icon} ${t.description} → ${t.assigned_category}</div>`;
        });
        
        html += '</div>';
    }
    
    html += '</div>';
    resultsDiv.innerHTML = html;
    resultsDiv.style.display = 'block';
}

// UPDATED: Process transactions with current month filtering option
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
        // Store files for analysis BEFORE processing
        await storeFilesForAnalysis(selectedFiles);

        const formData = new FormData();
        
        // Add each file to form data - CRITICAL: use 'files' as the field name
        selectedFiles.forEach((file, index) => {
            console.log(`Adding file to FormData: ${file.name} (${file.size} bytes)`);
            formData.append('files', file, file.name);  // Ensure filename is preserved
        });
        
        // Add processing options
        const autoUpdate = document.getElementById('autoUpdateBalances');
        const updateCategories = document.getElementById('updateCategories');
        const currentMonthOnly = document.getElementById('currentMonthOnly');
        
        formData.append('auto_update', autoUpdate ? autoUpdate.checked : true);
        formData.append('update_categories', updateCategories ? updateCategories.checked : true);
        formData.append('current_month_only', currentMonthOnly ? currentMonthOnly.checked : false);

        console.log('Sending files to server...');

        const response = await fetch('/api/upload-transactions', {
            method: 'POST',
            body: formData
        });

        console.log('Response status:', response.status);
        
        const responseText = await response.text();
        console.log('Response text:', responseText);

        let result;
        try {
            result = JSON.parse(responseText);
        } catch (e) {
            console.error('Failed to parse response as JSON:', e);
            throw new Error(`Server response was not valid JSON: ${responseText.substring(0, 200)}`);
        }
        
        if (response.ok && result.success) {
            showMessage('✅ ' + result.message, 'success');
            
            // Show details about what was processed
            if (result.categorization_preview) {
                showCategorizationPreview(result.categorization_preview);
            }
            
            // Clear files after successful processing
            setTimeout(() => {
                clearAllFilesQuietly();
            }, 2000);
            
        } else {
            throw new Error(result.error || 'Processing failed');
        }
    } catch (err) {
        console.error('Error processing transactions:', err);
        showMessage(`❌ Processing failed: ${err.message}`, 'error');
    } finally {
        // Restore button state
        processBtn.disabled = selectedFiles.length === 0;
        processBtn.innerHTML = selectedFiles.length > 0 ? 
            `🔄 Process ${selectedFiles.length} File(s)` : originalText;
    }
}

// UPDATED: Analyze transactions with current month filtering option
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
        // Store files for analysis BEFORE processing
        await storeFilesForAnalysis(selectedFiles);

        const formData = new FormData();
        
        // Add each file to form data
        selectedFiles.forEach(file => {
            formData.append('files', file);
        });
        
        // Set to analyze only (no balance updates)
        const updateCategories = document.getElementById('updateCategories');
        const currentMonthOnly = document.getElementById('currentMonthOnly');
        
        formData.append('auto_update', 'false');
        formData.append('update_categories', updateCategories?.checked.toString() || 'true');
        formData.append('current_month_only', currentMonthOnly?.checked.toString() || 'false');

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
            const filterMsg = result.current_month_filtering === true ? 
                ' (current month only)' : 
                result.current_month_filtering === false ?
                ' (all months)' : '';
            
            // Show success message BEFORE clearing files
            showTransactionResults({
                type: 'info',
                title: '📊 Analysis Complete',
                message: result.message,
                details: [
                    `Files analyzed: ${result.files_processed}`,
                    'No balances were updated',
                    `Category spending updated for reference${filterMsg}`
                ]
            });
            
            // Wait before clearing files
            setTimeout(() => {
                clearAllFilesQuietly();
            }, 1000);
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

// NEW: Debug function for transaction processing
async function debugTransactionProcessing() {
    const debugBtn = document.querySelector('button[onclick="debugTransactionProcessing()"]');
    const originalText = debugBtn ? debugBtn.textContent : '';
    
    if (debugBtn) {
        debugBtn.disabled = true;
        debugBtn.textContent = '🔍 Loading...';
    }
    
    try {
        console.log('=== TRANSACTION PROCESSING DEBUG ===');
        
        // Get debug info from API
        const response = await fetch('/api/debug-categories');
        const result = await response.json();
        
        if (result.success) {
            const debugData = result.data;
            
            // Show debug information
            const debugResults = document.getElementById('debugResults');
            const debugContent = document.getElementById('debugContent');
            
            if (debugResults && debugContent) {
                const currentMonth = debugData.current_month;
                const currentData = debugData.current_month_data || {};
                const allData = debugData.all_category_data || {};
                
                const totalCurrentSpending = Object.values(currentData).reduce((sum, val) => sum + (val || 0), 0);
                const categoriesWithSpending = Object.entries(currentData).filter(([k, v]) => v > 0);
                
                debugContent.innerHTML = `
                    <div style="font-family: monospace; font-size: 0.9rem;">
                        <h4>📊 Current Status (${currentMonth})</h4>
                        <div style="margin-bottom: 1rem;">
                            <strong>Total Category Spending:</strong> ${totalCurrentSpending.toFixed(2)}<br>
                            <strong>Categories with Spending:</strong> ${categoriesWithSpending.length}/6<br>
                            <strong>Available Months:</strong> ${debugData.all_months_available?.join(', ') || 'None'}
                        </div>
                        
                        <h4>💳 Card Balances</h4>
                        <div style="margin-bottom: 1rem;">
                            ${Object.entries(debugData.card_balances || {}).map(([name, balance]) => 
                                `<div>${name}: ${balance.toFixed(2)}</div>`
                            ).join('')}
                        </div>
                        
                        <h4>📈 Current Month Categories</h4>
                        <div style="margin-bottom: 1rem;">
                            ${Object.entries(currentData).map(([category, amount]) => 
                                `<div style="color: ${amount > 0 ? '#16a34a' : '#6b7280'}">
                                    ${category}: ${amount.toFixed(2)}
                                </div>`
                            ).join('')}
                        </div>
                        
                        <h4>🏷️ Categorization Examples</h4>
                        <div style="margin-bottom: 1rem; font-size: 0.8rem;">
                            ${Object.entries(debugData.categorization_examples || {}).map(([category, examples]) => 
                                `<div style="margin-bottom: 0.5rem;">
                                    <strong style="color: ${getCategoryColor(category)}">${category}:</strong> ${examples.join(', ')}
                                </div>`
                            ).join('')}
                        </div>
                        
                        <details style="margin-top: 1rem;">
                            <summary style="cursor: pointer; font-weight: bold;">Raw Data (Click to expand)</summary>
                            <pre style="background: #f8f9fa; padding: 1rem; border-radius: 4px; overflow-x: auto; margin-top: 0.5rem; max-height: 300px; overflow-y: auto;">${JSON.stringify(debugData, null, 2)}</pre>
                        </details>
                        
                        <div style="margin-top: 1rem; text-align: center;">
                            <button class="btn btn-secondary" onclick="hideDebugResults()">Close Debug Info</button>
                            <button class="btn btn-info" onclick="testCategorizationSample()" style="margin-left: 0.5rem;">🧪 Test Sample Categorization</button>
                        </div>
                    </div>
                `;
                
                debugResults.style.display = 'block';
                debugResults.scrollIntoView({ behavior: 'smooth' });
                
                // Also log to console
                console.log('Debug data:', debugData);
            }
        } else {
            throw new Error(result.error || 'Debug request failed');
        }
        
    } catch (err) {
        console.error('Debug error:', err);
        showMessage(`Debug failed: ${err.message}`, 'error');
    } finally {
        if (debugBtn) {
            debugBtn.disabled = false;
            debugBtn.textContent = originalText || '🔍 Debug Categories';
        }
    }
}

function hideDebugResults() {
    const debugResults = document.getElementById('debugResults');
    if (debugResults) {
        debugResults.style.display = 'none';
    }
}

// Helper function to show enhanced transaction results
function showTransactionResults(config) {
    const resultsDiv = document.getElementById('transactionResults');
    if (!resultsDiv) return;
    
    let categorizationHtml = '';
    
    // Show categorization preview if available
    if (config.categorization_preview && Object.keys(config.categorization_preview).length > 0) {
        categorizationHtml = `
            <div style="margin-top: 1.5rem; padding: 1rem; background: #f8f9fa; border-radius: 8px; border-left: 4px solid #28a745;">
                <h5 style="margin: 0 0 1rem 0; color: #28a745;">📊 Categorization Preview</h5>
                ${Object.entries(config.categorization_preview).map(([filename, transactions]) => `
                    <div style="margin-bottom: 1rem;">
                        <h6 style="margin: 0 0 0.5rem 0; font-weight: bold;">${filename}</h6>
                        <div style="display: grid; grid-template-columns: 2fr 1fr 1fr 1fr; gap: 0.5rem; font-size: 0.85rem; margin-bottom: 0.5rem; font-weight: bold; border-bottom: 1px solid #dee2e6; padding-bottom: 0.25rem;">
                            <div>Description</div>
                            <div>Original Category</div>
                            <div>Assigned Category</div>
                            <div>Amount</div>
                        </div>
                        ${transactions.slice(0, 8).map(transaction => {
                            const categoryColor = getCategoryColor(transaction.assigned_category);
                            return `
                                <div style="display: grid; grid-template-columns: 2fr 1fr 1fr 1fr; gap: 0.5rem; font-size: 0.8rem; margin-bottom: 0.25rem; padding: 0.25rem; background: white; border-radius: 4px;">
                                    <div style="overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="${escapeHtml(transaction.description)}">${escapeHtml(transaction.description.substring(0, 30))}${transaction.description.length > 30 ? '...' : ''}</div>
                                    <div style="color: #6b7280;">${escapeHtml(transaction.original_category || 'None')}</div>
                                    <div style="color: ${categoryColor}; font-weight: bold;">${transaction.assigned_category}</div>
                                    <div style="text-align: right;">$${transaction.amount.toFixed(2)}</div>
                                </div>
                            `;
                        }).join('')}
                        ${transactions.length > 8 ? `<div style="text-align: center; color: #6b7280; font-style: italic; margin-top: 0.5rem;">... and ${transactions.length - 8} more transactions</div>` : ''}
                    </div>
                `).join('')}
                <div style="margin-top: 1rem; font-size: 0.85rem; color: #6b7280;">
                    💡 <strong>Tip:</strong> If categorizations look incorrect, the transaction descriptions might need better keyword matching. Use the debug button below to investigate further.
                </div>
            </div>
        `;
    }
    
    resultsDiv.innerHTML = `
        <div class="results-card ${config.type}" style="position: relative;">
            <h4>${config.title}</h4>
            <p>${config.message}</p>
            ${config.details ? `
                <ul style="margin-top: 1rem; margin-left: 1rem;">
                    ${config.details.map(detail => `<li>${detail}</li>`).join('')}
                </ul>
            ` : ''}
            ${categorizationHtml}
            ${config.type === 'success' ? `
                <div style="margin-top: 1rem; text-align: center; display: flex; gap: 0.5rem; justify-content: center; flex-wrap: wrap;">
                    <button class="btn btn-info" onclick="debugTransactionProcessing()">
                        🔍 View Category Debug Info
                    </button>
                    <button class="btn btn-secondary" onclick="testCategorizationSample()">
                        🧪 Test Categorization
                    </button>
                </div>
            ` : ''}
            <div style="position: absolute; top: 10px; right: 10px; background: #28a745; color: white; padding: 0.25rem 0.5rem; border-radius: 4px; font-size: 0.8rem;">
                Message will persist for 3 seconds
            </div>
        </div>
    `;
    
    resultsDiv.style.display = 'block';
    resultsDiv.scrollIntoView({ behavior: 'smooth' });
}

// Helper function to get color for categories
function getCategoryColor(category) {
    const colors = {
        'Groceries': '#16a34a',      // Green
        'Food & Drinks': '#dc2626',  // Red
        'Shopping': '#2563eb',       // Blue
        'Services': '#7c3aed',       // Purple
        'Entertainment': '#ea580c',  // Orange
        'Other': '#6b7280'           // Gray
    };
    return colors[category] || '#6b7280';
}

// NEW: Test categorization function
async function testCategorizationSample() {
    console.log('Testing categorization sample...');
    
    const testTransactions = [
        { description: 'WHOLE FOODS MARKET #123', original_category: 'Supermarkets', memo: '' },
        { description: 'STARBUCKS COFFEE #456', original_category: 'Coffee Shops', memo: '' },
        { description: 'AMAZON.COM AMZN.COM/BILL', original_category: 'Shopping', memo: '' },
        { description: 'NETFLIX.COM', original_category: 'Subscription', memo: '' },
        { description: 'CHIPOTLE MEXICAN GRILL', original_category: 'Fast Food', memo: '' },
        { description: 'KROGER FUEL #789', original_category: 'Gas Stations', memo: '' }
    ];
    
    // Show loading state
    const testBtn = document.querySelector('button[onclick="testCategorizationSample()"]');
    const originalText = testBtn ? testBtn.textContent : '';
    if (testBtn) {
        testBtn.disabled = true;
        testBtn.textContent = '🧪 Testing...';
    }
    
    try {
        console.log('Sending test request to /api/test-categorization');
        
        const response = await fetch('/api/test-categorization', {
            method: 'POST',
            headers: { 
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            },
            body: JSON.stringify({ transactions: testTransactions })
        });
        
        console.log('Test response status:', response.status);
        
        if (!response.ok) {
            const errorText = await response.text();
            throw new Error(`HTTP ${response.status}: ${errorText}`);
        }
        
        const result = await response.json();
        console.log('Test categorization result:', result);
        
        if (result.success && result.results) {
            let testHtml = `
                <div style="margin-top: 1rem; padding: 1rem; background: #f0f9ff; border-radius: 8px; border-left: 4px solid #3b82f6;">
                    <h5 style="margin: 0 0 1rem 0; color: #3b82f6;">🧪 Categorization Test Results</h5>
                    <div style="display: grid; grid-template-columns: 2fr 1fr 1fr; gap: 0.5rem; font-size: 0.85rem; margin-bottom: 0.5rem; font-weight: bold; border-bottom: 1px solid #cbd5e1; padding-bottom: 0.25rem;">
                        <div>Test Description</div>
                        <div>Original</div>
                        <div>Assigned</div>
                    </div>
                    ${result.results.map(test => `
                        <div style="display: grid; grid-template-columns: 2fr 1fr 1fr; gap: 0.5rem; font-size: 0.8rem; margin-bottom: 0.25rem; padding: 0.25rem; background: white; border-radius: 4px;">
                            <div>${escapeHtml(test.input.description)}</div>
                            <div style="color: #6b7280;">${escapeHtml(test.input.original_category || 'None')}</div>
                            <div style="color: ${getCategoryColor(test.assigned_category)}; font-weight: bold;">${test.assigned_category}</div>
                        </div>
                    `).join('')}
                    <button class="btn btn-small" onclick="this.parentElement.remove()" style="margin-top: 0.5rem;">Close Test</button>
                </div>
            `;
            
            const resultsDiv = document.getElementById('transactionResults');
            if (resultsDiv) {
                resultsDiv.insertAdjacentHTML('beforeend', testHtml);
            } else {
                // If no results div, show in a modal or alert
                const summaryDiv = document.createElement('div');
                summaryDiv.innerHTML = testHtml;
                document.body.appendChild(summaryDiv);
            }
        } else {
            throw new Error('Test categorization returned no results');
        }
        
    } catch (err) {
        console.error('Test categorization error:', err);
        showMessage(`Test categorization failed: ${err.message}`, 'error');
        
        // Also show detailed error for debugging
        alert(`Test Categorization Debug Info:
        
Error: ${err.message}

Check the browser console for more details. The test endpoint might not be implemented correctly on the backend.`);
    } finally {
        // Restore button state
        if (testBtn) {
            testBtn.disabled = false;
            testBtn.textContent = originalText || '🧪 Test Sample Categorization';
        }
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
    window.clearAllFilesQuietly = clearAllFilesQuietly;
    window.processTransactions = processTransactions;
    window.analyzeOnly = analyzeOnly;
    window.debugTransactionProcessing = debugTransactionProcessing;
    window.hideDebugResults = hideDebugResults;
    window.testCategorizationSample = testCategorizationSample;
    window.getCategoryColor = getCategoryColor;
    window.showPersistentTransactionResults = showPersistentTransactionResults;
    window.clearTransactionResults = clearTransactionResults;
    window.finishProcessingAndClear = finishProcessingAndClear;
    window.uploadOriginalCSV = uploadOriginalCSV;
    window.analyzeCSVBeforeProcessing = analyzeCSVBeforeProcessing;
    window.smartCSVProcessing = smartCSVProcessing;
    window.testCategorizationWithRealData = testCategorizationWithRealData;
    window.showCategorizationTips = showCategorizationTips;
    window.storeFilesForAnalysis = storeFilesForAnalysis;
}