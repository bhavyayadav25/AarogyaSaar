import React from 'react';
export default class GlobalErrorBoundary extends React.Component {
  constructor(props) { super(props); this.state = { error: null }; }
  static getDerivedStateFromError(error) { return { error }; }
  componentDidCatch(error) { console.error('AarogyaSaar UI error', error); }
  render() {
    if (!this.state.error) return this.props.children;
    return <div className="fatal"><div className="fatal-art">♡</div><h1>We’re sorry — this page needs a fresh start.</h1><p>Your information is safe on the care service. Refresh the page and try again.</p><button className="btn btn-primary" onClick={() => window.location.reload()}>Refresh</button></div>;
  }
}
