import React from 'react'
import {
  ArrowRight,
  ArrowUpRight,
  ChevronRight,
  MoveRight,
  Radar,
  Rocket,
  Network,
  CircleArrowRight
} from "lucide-react";
export default function Landing({ onNavigate }) {
  return (
    <div className="landing-full">
        <div style={{ textAlign: 'center', marginBottom: 28 }}>
          <div className="brand-title">TRACELY AI</div>
        </div>
      <div className="landing-card cards-wrapper" style={{ marginTop: 48 }}>

        <div className="feature-grid" style={{ marginTop: 22 }}>
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
            <div className="feature-sub">Displays observed authentication relationships between anonymized accounts and computers, with event counts and bounded graph views.</div>
          </div>

          <div className="feature-panel"  >
            <div className="feature-panel-h">
              <div className="feature-icon" >
                <Radar/>
              </div>
              <div>
                <div className="feature-label">Fast investigations</div>
                <div className="feature-value">Actionable signals</div>
              </div>
            </div>
            <div className="feature-sub">Compares observed user-hours with prior behavioral baselines and shows evidence behind unusual activity.</div>
          </div>

          <div className="feature-panel">
            <div className="feature-panel-h">
              <div className="feature-icon">
                <Rocket/>
              </div>
              <div>
                <div className="feature-label">DYNAMIC RISK SCORING</div>
                <div className="feature-value">Optimized Risk Engine</div>
              </div>
            </div>
            <div className="feature-sub">Compares Isolation Forest, PCA and an optional dense autoencoder using temporal validation. Measured reports show the selected model, weights, limitations and held-out results.</div>
          </div>
        </div>

        <div className="hero-description" style={{ color: 'var(--t2)', marginTop: 25, fontSize:14, textAlign: 'center' ,padding:15, }}>
            Tracely AI supports reproducible behavioral anomaly review. Risk indices are not probabilities, and an anomaly does not establish compromise or employee intent.
        </div>


        <div style={{ display: 'flex', justifyContent: 'center', gap: 12, marginTop: 80 ,marginBottom: 80 , padding:10}}>
          {/* <button className="btn btn-primary" onClick={() => onNavigate?.('overview')}>Explore it now ..</button> */}
            <div className="cta-container">
              <button
                className="button2 cta-btn"
                onClick={() => onNavigate?.('overview')}
              >
                Explore it now
                <CircleArrowRight size={36} strokeWidth={0.85} className="text-black" />
              </button>
            </div>
        </div>
        <div style={{ marginTop: 16, color: 'var(--t3)', fontSize: 13, textAlign: 'center' }}>
          © {new Date().getFullYear()} Tracely AI — Behavioral anomaly review
        </div>
      </div>
    </div>
  )
}
