import React from 'react';

/**
 * Keeps one broken route from becoming a blank workspace. Render failures are
 * contained to the current role area and give the user a safe recovery path.
 */
export default class RouteErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    console.error('AarogyaSaar route render error', error, info);
  }

  retry = () => this.setState({ error: null });

  goHome = () => {
    window.location.assign(this.props.homePath || '/');
  };

  render() {
    if (!this.state.error) return this.props.children;
    const { title = 'This workspace needs a fresh start.', homeLabel = 'Return to workspace' } = this.props;
    return (
      <section className="route-error-shell" role="alert" aria-live="assertive">
        <div className="route-error-card">
          <div className="route-error-icon" aria-hidden="true">!</div>
          <div>
            <div className="eyebrow">AarogyaSaar</div>
            <h1>{title}</h1>
            <p>We could not display this screen safely. Your saved information has not been changed.</p>
            <div className="route-error-actions">
              <button type="button" className="btn btn-primary" onClick={this.retry}>Try this screen again</button>
              <button type="button" className="btn btn-light" onClick={this.goHome}>{homeLabel}</button>
            </div>
          </div>
        </div>
      </section>
    );
  }
}
