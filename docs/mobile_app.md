# Mobile App Architecture & Setup Guide

## Overview

The mobile app provides **read-only access** to your spending data with a focus on quick budget checks and spending alerts. This maintains security while giving you convenient access to key information.

## Architecture

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│                 │    │                 │    │                 │
│   Mobile App    │◄───│  Flask API      │◄───│ Credit Card     │
│   (React Native)│    │  Server         │    │ Tracker         │
│   - Read Only   │    │  - REST API     │    │ - Encrypted     │
│   - Budget View │    │  - File Upload  │    │ - Local Storage │
│   - Alerts      │    │  - Analysis     │    │ - CLI Tools     │
│                 │    │                 │    │                 │
└─────────────────┘    └─────────────────┘    └─────────────────┘
        │                       │                       │
        │                       │                       │
        ▼                       ▼                       ▼
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Push Notifications│    │   Web Frontend  │    │  Transaction    │
│   - Budget Alerts   │    │   - Full Admin  │    │  CSV Files      │
│   - Due Date Reminders│  │   - Analysis    │    │  - Bank Downloads│
│   - Spending Warnings│   │   - Management  │    │  - Auto Process │
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

## Mobile App Features (Read-Only)

### 🏠 Dashboard
- Current month spending vs budget
- Days until next due date
- Available credit summary
- Quick spending status

### 📊 Budget Overview
- Category spending breakdown
- Progress bars for each category
- Over-budget alerts
- Spending trends (simple)

### 📅 Due Dates
- Next 3 due dates
- Payment amounts
- Days remaining
- Quick reminders

### 🔔 Notifications
- Budget exceeded alerts
- Due date reminders (3, 1 day before)
- Weekly spending summaries

## Technology Stack

### Option 1: React Native (Recommended)
**Pros:** Cross-platform, web-like development, good performance
**Cons:** Requires Node.js setup

### Option 2: Flutter
**Pros:** Native performance, single codebase
**Cons:** Dart language learning curve

### Option 3: Native iOS (Swift)
**Pros:** Best iOS integration, native performance
**Cons:** iOS only, requires Xcode

## Setup Instructions

### Prerequisites
1. Your Flask API server running on Mac
2. API accessible on local network
3. Mobile device on same network

### Option 1: React Native Setup

#### 1. Install React Native CLI
```bash
# Install Node.js and npm first
npm install -g react-native-cli
npm install -g @react-native-community/cli
```

#### 2. Create Mobile App
```bash
npx react-native init CreditCardTracker
cd CreditCardTracker
```

#### 3. Install Dependencies
```bash
npm install @react-navigation/native
npm install @react-navigation/bottom-tabs
npm install react-native-vector-icons
npm install @react-native-async-storage/async-storage
npm install react-native-push-notification
npm install axios
```

#### 4. Key Configuration Files

**API Configuration (`src/config/api.js`):**
```javascript
const API_BASE_URL = 'http://192.168.1.100:5000/api'; // Your Mac's IP

export const apiClient = {
  getSummary: () => fetch(`${API_BASE_URL}/mobile-summary`),
  getDueDates: () => fetch(`${API_BASE_URL}/summary`),
  getBudgets: () => fetch(`${API_BASE_URL}/summary`),
};
```

**Main App Structure (`App.js`):**
```javascript
import React from 'react';
import { NavigationContainer } from '@react-navigation/native';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import DashboardScreen from './src/screens/DashboardScreen';
import BudgetScreen from './src/screens/BudgetScreen';
import DueDatesScreen from './src/screens/DueDatesScreen';

const Tab = createBottomTabNavigator();

export default function App() {
  return (
    <NavigationContainer>
      <Tab.Navigator>
        <Tab.Screen name="Dashboard" component={DashboardScreen} />
        <Tab.Screen name="Budget" component={BudgetScreen} />
        <Tab.Screen name="Due Dates" component={DueDatesScreen} />
      </Tab.Navigator>
    </NavigationContainer>
  );
}
```

#### 5. Sample Dashboard Screen (`src/screens/DashboardScreen.js`)
```javascript
import React, { useState, useEffect } from 'react';
import {
  View, Text, StyleSheet, RefreshControl, ScrollView,
  Alert, StatusBar
} from 'react-native';
import { apiClient } from '../config/api';

export default function DashboardScreen() {
  const [data, setData] = useState(null);
  const [refreshing, setRefreshing] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
    try {
      const response = await apiClient.getSummary();
      const result = await response.json();
      
      if (result.success) {
        setData(result.data);
      } else {
        Alert.alert('Error', 'Failed to load data');
      }
    } catch (error) {
      Alert.alert('Network Error', 'Cannot connect to server');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  const onRefresh = () => {
    setRefreshing(true);
    loadData();
  };

  if (loading) {
    return (
      <View style={styles.container}>
        <Text>Loading...</Text>
      </View>
    );
  }

  return (
    <ScrollView
      style={styles.container}
      refreshControl={
        <RefreshControl refreshing={refreshing} onRefresh={onRefresh} />
      }
    >
      <StatusBar barStyle="dark-content" />
      
      {/* Spending Summary */}
      <View style={styles.card}>
        <Text style={styles.cardTitle}>💰 This Month</Text>
        <View style={styles.summaryRow}>
          <View style={styles.summaryItem}>
            <Text style={styles.summaryLabel}>Spent</Text>
            <Text style={styles.summaryValue}>
              ${data?.total_spending?.toFixed(2) || '0.00'}
            </Text>
          </View>
          <View style={styles.summaryItem}>
            <Text style={styles.summaryLabel}>Left</Text>
            <Text style={[
              styles.summaryValue,
              { color: data?.left_to_spend >= 0 ? '#22c55e' : '#ef4444' }
            ]}>
              ${Math.abs(data?.left_to_spend || 0).toFixed(2)}
            </Text>
          </View>
        </View>
      </View>

      {/* Budget Status */}
      <View style={[
        styles.card,
        { backgroundColor: getBudgetStatusColor(data?.budget_status) }
      ]}>
        <Text style={styles.statusText}>
          {getBudgetStatusText(data?.budget_status)}
        </Text>
      </View>

      {/* Top Categories */}
      <View style={styles.card}>
        <Text style={styles.cardTitle}>📊 Top Categories</Text>
        {data?.top_categories?.map((category, index) => (
          <View key={index} style={styles.categoryRow}>
            <Text style={styles.categoryName}>{category.name}</Text>
            <Text style={styles.categoryAmount}>
              ${category.amount.toFixed(2)}
            </Text>
          </View>
        ))}
      </View>

      {/* Next Due Date */}
      {data?.next_due && (
        <View style={styles.card}>
          <Text style={styles.cardTitle}>📅 Next Due</Text>
          <Text style={styles.dueDateCard}>{data.next_due.card_name}</Text>
          <Text style={styles.dueDateInfo}>
            ${data.next_due.balance.toFixed(2)} in {data.next_due.days} days
          </Text>
        </View>
      )}
    </ScrollView>
  );
}

const getBudgetStatusColor = (status) => {
  switch (status) {
    case 'over': return '#fef2f2';
    case 'warning': return '#fefbf2';
    default: return '#f0fdf4';
  }
};

const getBudgetStatusText = (status) => {
  switch (status) {
    case 'over': return '🚨 Over Budget';
    case 'warning': return '⚠️ Close to Limit';
    default: return '✅ On Track';
  }
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#f9fafb',
    padding: 16,
  },
  card: {
    backgroundColor: 'white',
    borderRadius: 12,
    padding: 20,
    marginBottom: 16,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.1,
    shadowRadius: 4,
    elevation: 3,
  },
  cardTitle: {
    fontSize: 18,
    fontWeight: '600',
    marginBottom: 16,
    color: '#374151',
  },
  summaryRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
  },
  summaryItem: {
    alignItems: 'center',
  },
  summaryLabel: {
    fontSize: 14,
    color: '#6b7280',
    marginBottom: 4,
  },
  summaryValue: {
    fontSize: 24,
    fontWeight: 'bold',
    color: '#111827',
  },
  statusText: {
    fontSize: 16,
    fontWeight: '600',
    textAlign: 'center',
    color: '#374151',
  },
  categoryRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginBottom: 12,
  },
  categoryName: {
    fontSize: 14,
    color: '#374151',
  },
  categoryAmount: {
    fontSize: 14,
    fontWeight: '600',
    color: '#111827',
  },
  dueDateCard: {
    fontSize: 16,
    fontWeight: '600',
    color: '#374151',
    marginBottom: 4,
  },
  dueDateInfo: {
    fontSize: 14,
    color: '#6b7280',
  },
});
```

### Option 2: Native iOS App (Swift)

#### Key Files Structure
```
CreditCardTracker/
├── ContentView.swift          # Main dashboard
├── BudgetView.swift          # Budget breakdown
├── DueDatesView.swift        # Due dates list
├── NotificationManager.swift # Push notifications
├── APIClient.swift          # Network layer
└── Models/
    ├── SpendingSummary.swift
    ├── BudgetItem.swift
    └── DueDate.swift
```

#### Sample iOS Implementation (`APIClient.swift`)
```swift
import Foundation

class APIClient: ObservableObject {
    private let baseURL = "http://192.168.1.100:5000/api"
    
    func fetchMobileSummary() async throws -> SpendingSummary {
        guard let url = URL(string: "\(baseURL)/mobile-summary") else {
            throw APIError.invalidURL
        }
        
        let (data, _) = try await URLSession.shared.data(from: url)
        let response = try JSONDecoder().decode(APIResponse<SpendingSummary>.self, from: data)
        
        if response.success {
            return response.data
        } else {
            throw APIError.serverError(response.error ?? "Unknown error")
        }
    }
}

struct APIResponse<T: Codable>: Codable {
    let success: Bool
    let data: T
    let error: String?
}

enum APIError: Error {
    case invalidURL
    case serverError(String)
}
```

## Push Notifications Setup

### 1. Local Notifications (React Native)
```javascript
import PushNotification from 'react-native-push-notification';

// Configure push notifications
PushNotification.configure({
  onNotification: function(notification) {
    console.log('Notification:', notification);
  },
  requestPermissions: Platform.OS === 'ios',
});

// Schedule budget alert
const scheduleBudgetAlert = (amount, limit) => {
  if (amount > limit) {
    PushNotification.localNotification({
      title: 'Budget Alert! 🚨',
      message: `You've spent $${amount.toFixed(2)} of your $${limit.toFixed(2)} budget`,
      playSound: true,
    });
  }
};

// Schedule due date reminder
const scheduleDueDateReminder = (cardName, daysUntil, amount) => {
  PushNotification.localNotificationSchedule({
    title: 'Payment Due Soon! 📅',
    message: `${cardName}: $${amount.toFixed(2)} due in ${daysUntil} days`,
    date: new Date(Date.now() + 60 * 1000), // 1 minute from now
  });
};
```

### 2. Background Sync
```javascript
// Check for updates every hour when app is backgrounded
import BackgroundJob from 'react-native-background-job';

const backgroundSync = () => {
  BackgroundJob.start({
    jobKey: 'syncSpendingData',
    period: 3600000, // 1 hour
  });
};

BackgroundJob.register({
  jobKey: 'syncSpendingData',
  job: () => {
    // Fetch latest data
    // Check for budget overages
    // Send notifications if needed
  }
});
```

## Security Considerations

### API Security
1. **Local Network Only**: API only accessible on home network
2. **No Authentication Required**: Since it's local and read-only
3. **HTTPS Optional**: For local network, HTTP is acceptable
4. **Rate Limiting**: Prevent abuse with request limits

### Mobile App Security
1. **Read-Only**: Cannot modify any financial data
2. **Local Storage**: Minimal data caching
3. **Network Security**: Only connects to known local IP
4. **No Credentials**: No login or sensitive data stored

### Privacy Protection
1. **No Cloud Sync**: All data stays local
2. **No Analytics**: No tracking or data collection
3. **Offline Capable**: Core features work without network
4. **Secure Notifications**: No sensitive data in notification text

## Deployment Options

### Development Setup
1. Run Flask API on Mac: `python3 web_api_server.py`
2. Note your Mac's local IP address
3. Update mobile app API configuration
4. Run mobile app in development mode

### Production Setup
1. **Home Network**: API runs on always-on Mac/server
2. **Port Forwarding**: Optional for remote access
3. **DNS/mDNS**: Use `credittracker.local` instead of IP
4. **SSL Certificate**: For HTTPS if desired

## File Organization

```
credit-card-tracker/
├── credit_card_tracker.py     # Main tracker (combined)
├── transaction_processor.py   # Transaction processor
├── web_api_server.py         # Flask API server
├── web_frontend.html        # Web interface
├── mobile/                  # Mobile app folder
│   ├── CreditCardTracker/   # React Native app
│   │   ├── src/
│   │   │   ├── screens/
│   │   │   ├── components/
│   │   │   └── config/
│   │   └── package.json
│   └── ios/                # iOS native app (optional)
│       └── CreditCardTracker.xcodeproj
└── README.md               # Updated documentation
```

## Next Steps

1. **Choose Mobile Platform**: React Native (easiest) or Native iOS
2. **Set Up Development Environment**: Install tools and dependencies  
3. **Configure API Connection**: Update mobile app with your Mac's IP
4. **Test on Local Network**: Ensure mobile app can reach Flask API
5. **Add Push Notifications**: Set up local notifications for alerts
6. **Customize UI**: Match your personal preferences and needs

## Benefits of This Architecture

✅ **Security First**: All data stays local, encrypted storage maintained
✅ **Offline Capable**: Core CLI tools work without network
✅ **Multiple Interfaces**: CLI, Web, Mobile - use what works best for each situation
✅ **Read-Only Mobile**: Safe mobile access without risk of data corruption
✅ **Scalable**: Easy to add more features or interfaces later
✅ **Professional**: Suitable for a Security Director's requirements
✅ **Web-First**: Modern web interface for visual analysis and management
✅ **Mobile Responsive**: Web interface works on mobile devices too

The mobile app gives you quick budget insights and spending alerts while maintaining the security and offline nature of your existing system!