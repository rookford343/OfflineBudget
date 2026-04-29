// Card Management Functions

// Card Management Functions
async function loadCardsManagement() {
    try {
        const response = await fetch('/api/cards');
        const result = await response.json();
        
        if (result.success) {
            displayCardsManagement(result.data);
        }
    } catch (err) {
        console.error('Error loading cards for management:', err);
    }
}

function displayCardsManagement(cards) {
    const cardsManagement = document.getElementById('cardsManagement');
    
    if (!cards || cards.length === 0) {
        cardsManagement.innerHTML = '<div class="empty-state"><div class="empty-state-icon">💳</div>No credit cards configured<br><small>Add your first card using the form above</small></div>';
        return;
    }

    cardsManagement.innerHTML = cards.map(card => `
        <div class="card" style="margin-bottom: 1rem;">
            <div class="list-item">
                <div class="item-info">
                    <div class="item-name">${escapeHtml(card.name)}</div>
                    <div class="item-details">
                        Limit: ${formatCurrency(card.credit_limit)} • 
                        Available: ${formatCurrency(card.available_credit)} • 
                        Statement: ${card.statement_date}th • 
                        Due: ${card.due_date}th
                        ${card.description ? '<br>' + escapeHtml(card.description) : ''}
                    </div>
                </div>
                <div class="item-actions" style="display: flex; gap: 0.5rem; flex-shrink: 0;">
                    <button class="btn btn-small btn-warning" 
                            onclick="editCard('${escapeHtml(card.name)}')"
                            style="z-index: 5; position: relative;">
                        ✏️ Edit
                    </button>
                    <button class="btn btn-small btn-danger" 
                            onclick="removeCard('${escapeHtml(card.name)}')"
                            style="z-index: 5; position: relative;">
                        🗑️ Remove
                    </button>
                </div>
            </div>
            <div style="margin-top: 1rem; padding-top: 1rem; border-top: 1px solid var(--border-color);">
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 1rem;">
                    <div>
                        <strong>Current Balance:</strong><br>
                        <span class="item-amount ${card.current_balance > 0 ? 'status-warning' : 'status-good'}">
                            ${formatCurrency(card.current_balance)}
                        </span>
                    </div>
                    <div>
                        <strong>Balance Due:</strong><br>
                        <span class="item-amount ${card.balance_due > 0 ? 'status-warning' : 'status-good'}">
                            ${formatCurrency(card.balance_due)}
                        </span>
                    </div>
                </div>
            </div>
        </div>
    `).join('');
}

function showAddCardForm() {
    const form = document.getElementById('addCardForm');
    form.style.display = 'block';
    form.style.zIndex = '10';
    
    // Scroll to form and focus first field
    form.scrollIntoView({ behavior: 'smooth', block: 'start' });
    setTimeout(() => {
        document.getElementById('cardName').focus();
    }, 100);
}

function hideAddCardForm() {
    const form = document.getElementById('addCardForm');
    form.style.display = 'none';
    
    // Reset form
    const formElement = document.getElementById('addCardFormElement');
    if (formElement) {
        formElement.reset();
    }
}

async function addCard(event) {
    event.preventDefault();
    
    const buttonState = setButtonLoading('addCardSubmitBtn', '⏳ Adding Card...');
    
    try {
        const formData = new FormData(event.target);
        const cardData = {
            name: formData.get('cardName'),
            credit_limit: parseFloat(formData.get('creditLimit')),
            statement_date: parseInt(formData.get('statementDate')),
            due_date: parseInt(formData.get('dueDate')),
            current_balance: parseFloat(formData.get('currentBalance')) || 0,
            balance_due: parseFloat(formData.get('balanceDue')) || 0,
            description: formData.get('cardDescription') || ''
        };

        const response = await fetch('/api/cards', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(cardData)
        });

        const result = await response.json();
        
        if (result.success) {
            showMessage('Card added successfully!', 'success');
            hideAddCardForm();
            loadCardsManagement();
            event.target.reset();
        } else {
            showMessage('Error adding card: ' + result.error, 'error');
        }
    } catch (err) {
        showMessage('Error adding card: ' + err.message, 'error');
    } finally {
        if (buttonState) buttonState.restore();
    }
    
    return false;
}

async function removeCard(cardName) {
    if (!confirm(`Are you sure you want to remove the card "${cardName}"?\n\nThis action cannot be undone.`)) {
        return;
    }

    try {
        console.log('Removing card:', cardName);
        
        const response = await fetch(`/api/cards/${encodeURIComponent(cardName)}`, {
            method: 'DELETE'
        });

        const result = await response.json();
        console.log('Remove card response:', result);
        
        if (result.success) {
            showMessage('Card removed successfully!', 'success');
            loadCardsManagement();
            
            // Hide edit form if it was open for this card
            const editForm = document.getElementById('editCardForm');
            if (editForm && editForm.style.display !== 'none') {
                const editCardName = document.getElementById('editCardName');
                if (editCardName && editCardName.value === cardName) {
                    hideEditCardForm();
                }
            }
        } else {
            showMessage('Error removing card: ' + result.error, 'error');
        }
    } catch (err) {
        console.error('Error removing card:', err);
        showMessage('Error removing card: ' + err.message, 'error');
    }
}

async function editCard(cardName) {
    console.log('Editing card:', cardName);
    
    try {
        // Get current card data from API
        const response = await fetch('/api/cards');
        const result = await response.json();
        
        if (!result.success) {
            showMessage('Error loading card data: ' + result.error, 'error');
            return;
        }
        
        // Find the specific card
        const card = result.data.find(c => c.name === cardName);
        if (!card) {
            showMessage('Card not found: ' + cardName, 'error');
            return;
        }
        
        // Show edit form (we'll create this)
        showEditCardForm(card);
        
    } catch (err) {
        console.error('Error loading card for editing:', err);
        showMessage('Error loading card data: ' + err.message, 'error');
    }
}

function showEditCardForm(card) {
    // Hide add card form if it's open
    hideAddCardForm();
    
    // Create or show edit form
    let editForm = document.getElementById('editCardForm');
    if (!editForm) {
        // Create edit form if it doesn't exist
        editForm = createEditCardForm();
        document.getElementById('cardsManagement').parentNode.insertBefore(editForm, document.getElementById('cardsManagement'));
    }
    
    // Populate form with card data
    document.getElementById('editCardName').value = card.name;
    document.getElementById('editCreditLimit').value = card.credit_limit;
    document.getElementById('editStatementDate').value = card.statement_date;
    document.getElementById('editDueDate').value = card.due_date;
    document.getElementById('editCurrentBalance').value = card.current_balance;
    document.getElementById('editBalanceDue').value = card.balance_due;
    document.getElementById('editCardDescription').value = card.description || '';
    
    // Store original name for API call
    editForm.setAttribute('data-original-name', card.name);
    
    // Show form
    editForm.style.display = 'block';
    editForm.scrollIntoView({ behavior: 'smooth', block: 'start' });
    
    // Focus first editable field (not the name, since it's readonly)
    setTimeout(() => {
        document.getElementById('editCreditLimit').focus();
    }, 100);
}

function createEditCardForm() {
    const formHTML = `
        <div id="editCardForm" class="card" style="display: none; margin-bottom: 2rem; z-index: 10;">
            <h3>Edit Credit Card</h3>
            <form onsubmit="return updateCard(event)" id="editCardFormElement">
                <div class="form-row">
                    <div class="form-group">
                        <label class="form-label" for="editCardName">Card Name *</label>
                        <input type="text" class="form-input" id="editCardName" name="editCardName" readonly
                            style="background-color: #f5f5f5; cursor: not-allowed;">
                        <small class="item-details">Card name cannot be changed</small>
                    </div>
                    <div class="form-group">
                        <label class="form-label" for="editCreditLimit">Credit Limit *</label>
                        <input type="number" class="form-input" id="editCreditLimit" name="editCreditLimit" required 
                            step="0.01" min="0">
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label class="form-label" for="editStatementDate">Statement Date *</label>
                        <input type="number" class="form-input" id="editStatementDate" name="editStatementDate" required 
                            min="1" max="31">
                        <small class="item-details">Day of month (1-31)</small>
                    </div>
                    <div class="form-group">
                        <label class="form-label" for="editDueDate">Due Date *</label>
                        <input type="number" class="form-input" id="editDueDate" name="editDueDate" required 
                            min="1" max="31">
                        <small class="item-details">Day of month (1-31)</small>
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label class="form-label" for="editCurrentBalance">Current Balance</label>
                        <input type="number" class="form-input" id="editCurrentBalance" name="editCurrentBalance" 
                            step="0.01" min="0">
                        <small class="item-details">New spending since last statement</small>
                    </div>
                    <div class="form-group">
                        <label class="form-label" for="editBalanceDue">Balance Due</label>
                        <input type="number" class="form-input" id="editBalanceDue" name="editBalanceDue" 
                            step="0.01" min="0">
                        <small class="item-details">Previous statement balance</small>
                    </div>
                </div>
                <div class="form-group">
                    <label class="form-label" for="editCardDescription">Description</label>
                    <input type="text" class="form-input" id="editCardDescription" name="editCardDescription">
                </div>
                <div class="form-group">
                    <button type="submit" class="btn btn-success" id="editCardSubmitBtn">Update Card</button>
                    <button type="button" class="btn btn-secondary" onclick="hideEditCardForm()">Cancel</button>
                </div>
            </form>
        </div>
    `;
    
    const formContainer = document.createElement('div');
    formContainer.innerHTML = formHTML;
    return formContainer.firstElementChild;
}

async function updateCard(event) {
    event.preventDefault();
    
    const buttonState = setButtonLoading('editCardSubmitBtn', '⏳ Updating Card...');
    const form = event.target;
    const originalName = form.parentElement.getAttribute('data-original-name');
    
    try {
        const formData = new FormData(event.target);
        const cardData = {
            credit_limit: parseFloat(formData.get('editCreditLimit')),
            statement_date: parseInt(formData.get('editStatementDate')),
            due_date: parseInt(formData.get('editDueDate')),
            current_balance: parseFloat(formData.get('editCurrentBalance')) || 0,
            balance_due: parseFloat(formData.get('editBalanceDue')) || 0,
            description: formData.get('editCardDescription') || ''
        };

        console.log('Updating card:', originalName, cardData);

        const response = await fetch(`/api/cards/${encodeURIComponent(originalName)}`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(cardData)
        });

        const result = await response.json();
        console.log('Update card response:', result);
        
        if (result.success) {
            showMessage('Card updated successfully!', 'success');
            hideEditCardForm();
            loadCardsManagement();
        } else {
            showMessage('Error updating card: ' + result.error, 'error');
        }
    } catch (err) {
        console.error('Error updating card:', err);
        showMessage('Error updating card: ' + err.message, 'error');
    } finally {
        if (buttonState) buttonState.restore();
    }
    
    return false;
}

function hideEditCardForm() {
    const form = document.getElementById('editCardForm');
    if (form) {
        form.style.display = 'none';
        
        // Reset form
        const formElement = document.getElementById('editCardFormElement');
        if (formElement) {
            formElement.reset();
        }
    }
}