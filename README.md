````markdown
# Tracely AI

Tracely AI is an insider threat detection system that uses **User and Entity Behavior Analytics (UEBA)** to identify unusual user activity.

It analyzes employee activity such as logins, file access, USB usage, and emails, then uses machine learning to detect abnormal behavior and assign risk levels.

## Features

- User behavior analysis
- Insider threat detection
- Anomaly detection using Isolation Forest and Autoencoder
- Risk scoring with multiple risk levels
- Threat alerts and user monitoring
- Interactive React dashboard
- REST API for accessing threat and user data

## Tech Stack

- **Frontend:** React.js
- **Backend:** Python, Flask
- **Machine Learning:** Scikit-learn, Isolation Forest, Autoencoder
- **Data Processing:** Pandas, NumPy
- **Dataset:** CERT Insider Threat Dataset / CERT-like generated data

## How It Works

```text
Employee Activity Logs
        ↓
Data Processing
        ↓
Feature Engineering
        ↓
Anomaly Detection
        ↓
Risk Scoring
        ↓
Threat Alerts
        ↓
React Dashboard
````

## Run Locally

### 1. Clone the repository

```bash
git clone <repository-url>
cd "Tracely AI"
```

### 2. Install dependencies

```bash
pip install -r requirements.txt

cd frontend
npm install
cd ..
```

### 3. Start the application

```bash
bash start.sh
```

The backend and frontend will start automatically.

## Project Structure

```text
Tracely AI/
├── data/
├── scripts/
├── src/
│   ├── pipeline/
│   ├── models/
│   └── api/
├── frontend/
├── requirements.txt
└── start.sh
```

## Author

**Gaurav Kumar**

```
```
