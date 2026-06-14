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
        <div style={{ textAlign: 'center', marginBottom: 50 }}>
          <div  className="brand-title" style={{ fontSize: 55, fontWeight: 800, color: '#c4e201', letterSpacing: '.16em' }}>TRACELY AI</div>
    
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
            <div className="feature-sub">Maps the hidden interactions between users, devices, and files to uncover coordinated anomalies and lateral movement that traditional rules miss.</div>
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
            <div className="feature-sub">Evaluates behavior against an employee's historical baseline to generate prioritized risk scores, helping analysts focus instantly on high-confidence alerts</div>
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
            <div className="feature-sub">Combines lightning-fast tree models with deep learning networks using an optimized 60:40 split. It instantly transforms complex, high-dimensional activity logs into clear, prioritized threat levels in under 25 milliseconds</div>
          </div>
        </div>

        <div className="hero-description" style={{ color: 'var(--t2)', marginTop: 25, fontSize:14, textAlign: 'center' ,padding:15, }}>
            Tracely AI transforms enterprise logs into high-confidence anomaly alerts, giving small security teams the visual tools needed to investigate threats instantly.
        </div>


        <div style={{ display: 'flex', justifyContent: 'center', gap: 12, marginTop: 80 ,marginBottom: 80 , padding:10}}>
          {/* <button className="btn btn-primary" onClick={() => onNavigate?.('overview')}>Explore it now ..</button> */}
          <div className="cta-container">
                <button
                    className="button2" 
                    // style = {{padding:30 , paddingTop:18 , paddingBottom:18 , fontSize:18}}
                    onClick={() => onNavigate?.('overview')}
                >
                    Explore it now 
              
                      <CircleArrowRight size={50} strokeWidth={0.85}  className="text-black" />
         
                    
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
