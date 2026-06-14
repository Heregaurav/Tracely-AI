import React from 'react'
import {
  ArrowRight,
  ArrowUpRight,
  ChevronRight,
  MoveRight,
  Radar,
  Rocket,
  Network
} from "lucide-react";
export default function Landing({ onNavigate }) {
  return (
    <div className="landing-full">
        <div style={{ textAlign: 'center', marginBottom: 30 }}>
          <div  className="brand-title" style={{ fontSize: 55, fontWeight: 800, color: 'var(--accent)', letterSpacing: '.16em' }}>TRACELY AI</div>
          <h1 style={{ marginTop: 8, fontSize: 20, lineHeight: 1.05 }}> Insider Thread Detector  </h1>
        </div>
      <div className="landing-card">
        <div className="hero-description" style={{ color: 'var(--t2)', marginTop: 15, fontSize: 15, textAlign: 'center' ,padding:15, }}>
          Tracely AI analyzes user activity, telemetry and relationship signals to surface suspicious connection
          patterns and prioritize high-confidence anomalies for investigation. Fast to deploy, interpretable scores,
          and visual tools for small security teams.
        </div>

        <div className="feature-grid" style={{ marginTop: 18 }}>
          <div className="feature-panel">
            <div className="feature-panel-h">
              <div className="feature-icon">
                <Network/>
              </div>
              <div>
                <div className="feature-label">Graph-first</div>
                <div className="feature-value">Relationship scoring</div>
              </div>
            </div>
            <div className="feature-sub">Compute centrality and intensity metrics to detect cross-entity anomalies.</div>
          </div>

          <div className="feature-panel">
            <div className="feature-panel-h">
              <div className="feature-icon">
                <Radar/>
              </div>
              <div>
                <div className="feature-label">Fast investigations</div>
                <div className="feature-value">Actionable signals</div>
              </div>
            </div>
            <div className="feature-sub">Prioritize high-risk subjects and streamline analyst workflows.</div>
          </div>

          <div className="feature-panel">
            <div className="feature-panel-h">
              <div className="feature-icon">
                <Rocket/>
              </div>
              <div>
                <div className="feature-label">Lightweight</div>
                <div className="feature-value">Easy to deploy</div>
              </div>
            </div>
            <div className="feature-sub">Small footprint, clear outputs — designed for practical use.</div>
          </div>
        </div>

        <div style={{ display: 'flex', justifyContent: 'center', gap: 12, marginTop: 80 ,marginBottom: 80 , padding:10}}>
          {/* <button className="btn btn-primary" onClick={() => onNavigate?.('overview')}>Explore it now ..</button> */}
          <div className="cta-container">
                <button
                    className="btn btn-primary" 
                    style = {{padding:30 , paddingTop:18 , paddingBottom:18 , fontSize:18}}
                    onClick={() => onNavigate?.('overview')}
                >
                    Explore it now ..
                    <ArrowRight/>
                </button>
                </div>
        </div>
        <div style={{ marginTop: 16, color: 'var(--t3)', fontSize: 13, textAlign: 'center' }}>
          © {new Date().getFullYear()} Tracely AI — Insider Thread detection 
        </div>
      </div>
    </div>
  )
}
