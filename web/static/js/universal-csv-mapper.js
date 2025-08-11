// Universal CSV Mapper - Handles CSV files from any bank
// Converts any bank's CSV format to the standard 6-column format expected by the server

class UniversalCSVMapper {
    constructor() {
        // Define common column name variations across all banks
        this.columnMappings = {
            'transaction_date': [
                'transaction date', 'trans date', 'date', 'transaction_date',
                'posted date', 'post date', 'posting date', 'effective date',
                'settlement date', 'value date', 'trade date'
            ],
            'post_date': [
                'post date', 'posted date', 'posting date', 'settlement date',
                'effective date', 'transaction date', 'date'
            ],
            'description': [
                'description', 'merchant', 'payee', 'memo', 'details',
                'transaction details', 'reference', 'particulars', 'narrative'
            ],
            'category': [
                'category', 'type', 'transaction type', 'expense category',
                'spending category', 'merchant category', 'mcc description'
            ],
            'type': [
                'type', 'transaction type', 'debit/credit', 'dr/cr',
                'transaction code', 'entry type', 'direction'
            ],
            'amount': [
                'amount', 'transaction amount', 'charge amount', 'value',
                'debit amount', 'credit amount', 'net amount', 'total'
            ]
        };
        
        // Bank-specific patterns for better detection and handling
        this.bankPatterns = {
            'chase': {
                expectedColumns: ['Transaction Date', 'Post Date', 'Description', 'Category', 'Type', 'Amount'],
                amountColumn: 'Amount',
                dateFormat: 'MM/DD/YYYY',
                identifiers: ['chase', 'jpmorgan']
            },
            'bank_of_america': {
                expectedColumns: ['Date', 'Description', 'Amount', 'Running Bal.'],
                amountColumn: 'Amount',
                dateFormat: 'MM/DD/YYYY',
                identifiers: ['bank of america', 'boa', 'running bal']
            },
            'wells_fargo': {
                expectedColumns: ['Date', 'Amount', 'Check Number', 'Description'],
                amountColumn: 'Amount',
                dateFormat: 'MM/DD/YYYY',
                identifiers: ['wells fargo', 'wells', 'check number']
            },
            'citi': {
                expectedColumns: ['Date', 'Description', 'Debit', 'Credit'],
                amountColumn: ['Debit', 'Credit'],
                dateFormat: 'MM/DD/YYYY',
                identifiers: ['citi', 'citibank']
            },
            'capital_one': {
                expectedColumns: ['Transaction Date', 'Posted Date', 'Card No.', 'Description', 'Category', 'Debit', 'Credit'],
                amountColumn: ['Debit', 'Credit'],
                dateFormat: 'YYYY-MM-DD',
                identifiers: ['capital one', 'capitalone', 'card no.']
            },
            'discover': {
                expectedColumns: ['Trans. Date', 'Post Date', 'Description', 'Amount', 'Category'],
                amountColumn: 'Amount',
                dateFormat: 'MM/DD/YYYY',
                identifiers: ['discover']
            },
            'american_express': {
                expectedColumns: ['Date', 'Description', 'Card Member', 'Account #', 'Amount'],
                amountColumn: 'Amount',
                dateFormat: 'MM/DD/YYYY',
                identifiers: ['american express', 'amex', 'card member']
            }
        };
    }
    
    /**
     * Detect bank from filename or CSV headers
     * @param {string} filename - The CSV filename
     * @param {Array} headers - Array of column headers
     * @returns {string} - Detected bank identifier
     */
    detectBank(filename, headers) {
        const name = filename.toLowerCase();
        const headerStr = headers.join(',').toLowerCase();
        
        // Check each bank pattern
        for (const [bankId, pattern] of Object.entries(this.bankPatterns)) {
            for (const identifier of pattern.identifiers) {
                if (name.includes(identifier) || headerStr.includes(identifier)) {
                    console.log(`🏦 Detected bank: ${bankId} (matched: ${identifier})`);
                    return bankId;
                }
            }
        }
        
        console.log('🏦 Bank not specifically detected, using generic processing');
        return 'generic';
    }
    
    /**
     * Check if a column name matches a target type
     * @param {string} columnName - Column header to check
     * @param {string} targetType - Target type to match against
     * @returns {boolean} - Whether the column matches the target type
     */
    mapColumn(columnName, targetType) {
        const normalized = columnName.toLowerCase().trim();
        const mappings = this.columnMappings[targetType] || [];
        
        for (const mapping of mappings) {
            if (normalized === mapping || normalized.includes(mapping) || mapping.includes(normalized)) {
                return true;
            }
        }
        return false;
    }
    
    /**
     * Convert any CSV to the standard 6-column format
     * @param {string} csvContent - Raw CSV content
     * @param {string} filename - Original filename
     * @returns {string} - Converted CSV content
     */
    convertToStandardFormat(csvContent, filename) {
        console.log(`🔄 Converting CSV: ${filename}`);
        
        const lines = csvContent.split('\n').filter(line => line.trim());
        if (lines.length < 2) {
            throw new Error('CSV file appears to be empty or invalid');
        }
        
        const originalHeaders = this.parseCSVLine(lines[0]);
        console.log('📋 Original headers:', originalHeaders);
        
        const bank = this.detectBank(filename, originalHeaders);
        console.log('🏦 Detected bank:', bank);
        
        // Create column mapping
        const columnMap = this.createColumnMapping(originalHeaders);
        console.log('🗺️ Column mapping:', columnMap);
        
        // Validate that we have essential columns
        if (!this.hasEssentialColumns(columnMap)) {
            console.warn('⚠️ Missing essential columns, proceeding with best-effort mapping');
        }
        
        // Convert to standard format
        const standardHeaders = ['Transaction Date', 'Post Date', 'Description', 'Category', 'Type', 'Amount'];
        const convertedLines = [standardHeaders.join(',')];
        
        // Process data rows
        let successfulRows = 0;
        for (let i = 1; i < lines.length; i++) {
            const row = this.parseCSVLine(lines[i]);
            if (row.length < 2) continue; // Skip empty rows
            
            const convertedRow = this.convertRow(row, columnMap, originalHeaders, bank);
            if (convertedRow) {
                convertedLines.push(this.formatCSVLine(convertedRow));
                successfulRows++;
            }
        }
        
        const result = convertedLines.join('\n');
        console.log(`✅ Converted ${successfulRows} rows to standard format`);
        console.log('📄 Sample converted rows:', convertedLines.slice(1, 4));
        
        return result;
    }
    
    /**
     * Parse a CSV line, handling quoted fields properly
     * @param {string} line - CSV line to parse
     * @returns {Array} - Array of field values
     */
    parseCSVLine(line) {
        const result = [];
        let current = '';
        let inQuotes = false;
        
        for (let i = 0; i < line.length; i++) {
            const char = line[i];
            
            if (char === '"') {
                inQuotes = !inQuotes;
            } else if (char === ',' && !inQuotes) {
                result.push(current.trim());
                current = '';
            } else {
                current += char;
            }
        }
        
        result.push(current.trim());
        return result.map(field => field.replace(/^"|"$/g, '')); // Remove surrounding quotes
    }
    
    /**
     * Format an array as a CSV line, adding quotes where necessary
     * @param {Array} fields - Array of field values
     * @returns {string} - Formatted CSV line
     */
    formatCSVLine(fields) {
        return fields.map(field => {
            const str = String(field || '');
            // Add quotes if field contains comma, quote, or newline
            if (str.includes(',') || str.includes('"') || str.includes('\n')) {
                return '"' + str.replace(/"/g, '""') + '"';
            }
            return str;
        }).join(',');
    }
    
    /**
     * Create mapping from original columns to our standard columns
     * @param {Array} headers - Original CSV headers
     * @returns {Object} - Column mapping object
     */
    createColumnMapping(headers) {
        const mapping = {};
        
        for (let i = 0; i < headers.length; i++) {
            const header = headers[i].toLowerCase().trim();
            
            if (this.mapColumn(header, 'transaction_date')) {
                mapping.transaction_date = i;
            }
            if (this.mapColumn(header, 'post_date')) {
                mapping.post_date = i;
            }
            if (this.mapColumn(header, 'description')) {
                mapping.description = i;
            }
            if (this.mapColumn(header, 'category')) {
                mapping.category = i;
            }
            if (this.mapColumn(header, 'type')) {
                mapping.type = i;
            }
            if (this.mapColumn(header, 'amount')) {
                mapping.amount = i;
            }
            
            // Handle special cases for banks with separate debit/credit columns
            if (header.includes('debit') && !header.includes('card')) {
                mapping.debit = i;
            }
            if (header.includes('credit') && !header.includes('card')) {
                mapping.credit = i;
            }
        }
        
        return mapping;
    }
    
    /**
     * Check if we have the essential columns for conversion
     * @param {Object} mapping - Column mapping object
     * @returns {boolean} - Whether essential columns are present
     */
    hasEssentialColumns(mapping) {
        return (mapping.transaction_date !== undefined || mapping.post_date !== undefined) &&
               mapping.description !== undefined &&
               (mapping.amount !== undefined || mapping.debit !== undefined || mapping.credit !== undefined);
    }
    
    /**
     * Convert a single row to standard format
     * @param {Array} row - Original row data
     * @param {Object} mapping - Column mapping
     * @param {Array} originalHeaders - Original headers for reference
     * @param {string} bank - Detected bank
     * @returns {Array|null} - Converted row or null if conversion failed
     */
    convertRow(row, mapping, originalHeaders, bank) {
        try {
            // Extract values using mapping with fallbacks
            const transDate = this.getFieldValue(row, mapping, ['transaction_date', 'post_date']) || '';
            const postDate = this.getFieldValue(row, mapping, ['post_date', 'transaction_date']) || '';
            const description = this.getFieldValue(row, mapping, ['description']) || 'Unknown Transaction';
            const category = this.getFieldValue(row, mapping, ['category']) || 'Other';
            const type = this.getFieldValue(row, mapping, ['type']) || 'Sale';
            
            // Handle amount - could be single column or debit/credit columns
            let amount = this.calculateAmount(row, mapping);
            
            // Normalize amount format
            amount = this.normalizeAmount(amount, type);
            
            return [transDate, postDate, description, category, type, amount];
            
        } catch (error) {
            console.warn('⚠️ Error converting row:', row, error);
            return null;
        }
    }
    
    /**
     * Get field value with fallback options
     * @param {Array} row - Row data
     * @param {Object} mapping - Column mapping
     * @param {Array} fieldTypes - Field types to try in order
     * @returns {string} - Field value or empty string
     */
    getFieldValue(row, mapping, fieldTypes) {
        for (const fieldType of fieldTypes) {
            if (mapping[fieldType] !== undefined && row[mapping[fieldType]]) {
                return row[mapping[fieldType]].toString().trim();
            }
        }
        return '';
    }
    
    /**
     * Calculate amount from single amount column or debit/credit columns
     * @param {Array} row - Row data
     * @param {Object} mapping - Column mapping
     * @returns {string} - Calculated amount
     */
    calculateAmount(row, mapping) {
        if (mapping.amount !== undefined) {
            return row[mapping.amount] || '0';
        } else if (mapping.debit !== undefined && mapping.credit !== undefined) {
            const debit = parseFloat(row[mapping.debit] || '0');
            const credit = parseFloat(row[mapping.credit] || '0');
            
            if (credit > 0) {
                return credit.toString();
            } else if (debit > 0) {
                return (-Math.abs(debit)).toString();
            } else {
                return '0';
            }
        } else if (mapping.debit !== undefined) {
            return (-Math.abs(parseFloat(row[mapping.debit] || '0'))).toString();
        } else if (mapping.credit !== undefined) {
            return parseFloat(row[mapping.credit] || '0').toString();
        } else {
            return '0';
        }
    }
    
    /**
     * Normalize amount format (ensure expenses are negative)
     * @param {string} amount - Raw amount value
     * @param {string} type - Transaction type
     * @returns {string} - Normalized amount
     */
    normalizeAmount(amount, type) {
        const numAmount = parseFloat(amount || '0');
        
        // If it's already negative, keep it negative
        if (numAmount < 0) {
            return numAmount.toString();
        }
        
        // If it's a credit/deposit/payment, keep it positive
        const creditTypes = ['credit', 'deposit', 'payment', 'refund', 'return'];
        if (creditTypes.some(ct => type.toLowerCase().includes(ct))) {
            return numAmount.toString();
        }
        
        // For most transactions (sales, purchases), make them negative
        return (-Math.abs(numAmount)).toString();
    }
    
    /**
     * Get bank-specific configuration
     * @param {string} bankId - Bank identifier
     * @returns {Object} - Bank configuration
     */
    getBankConfig(bankId) {
        return this.bankPatterns[bankId] || this.bankPatterns['generic'];
    }
}

// Make the class available globally
if (typeof window !== 'undefined') {
    window.UniversalCSVMapper = UniversalCSVMapper;
}

// Test function for different bank formats
window.testBankCSV = function(bankName) {
    const testData = {
        chase: `Transaction Date,Post Date,Description,Category,Type,Amount,Memo
08/01/2025,08/01/2025,Test Purchase,Shopping,Sale,-25.00,`,
        
        bank_of_america: `Date,Description,Amount,Running Bal.
08/01/2025,Test Purchase,-25.00,1000.00`,
        
        wells_fargo: `Date,Amount,Check Number,Description
08/01/2025,-25.00,,Test Purchase`,
        
        citi: `Date,Description,Debit,Credit
08/01/2025,Test Purchase,25.00,`,
        
        capital_one: `Transaction Date,Posted Date,Card No.,Description,Category,Debit,Credit
2025-08-01,2025-08-01,1234,Test Purchase,Shopping,25.00,`,
        
        discover: `Trans. Date,Post Date,Description,Amount,Category
08/01/2025,08/01/2025,Test Purchase,-25.00,Shopping`,
        
        american_express: `Date,Description,Card Member,Account #,Amount
08/01/2025,Test Purchase,JOHN DOE,1234,-25.00`
    };
    
    const csvContent = testData[bankName];
    if (!csvContent) {
        console.log('❌ Unknown bank. Available: chase, bank_of_america, wells_fargo, citi, capital_one, discover, american_express');
        return;
    }
    
    const blob = new Blob([csvContent], { type: 'text/csv' });
    const testFile = new File([blob], `${bankName}_test.csv`, { type: 'text/csv' });
    
    console.log(`🧪 Created ${bankName} test file`);
    if (typeof addFiles === 'function') {
        addFiles([testFile]);
    } else {
        console.log('📁 addFiles function not available. File created but not added to selection.');
    }
};

console.log('✅ Universal CSV Mapper loaded successfully');
console.log('🧪 Test with: testBankCSV("chase"), testBankCSV("bank_of_america"), etc.');