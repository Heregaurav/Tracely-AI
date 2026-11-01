import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.jsx'
import SessionGate from './components/SessionGate.jsx'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode><SessionGate><App/></SessionGate></React.StrictMode>
)
