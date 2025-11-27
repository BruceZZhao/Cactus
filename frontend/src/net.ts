// Network configuration for clean backend
const API_BASE = '';
const WS_BASE = (() => {
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
  return `${proto}://${window.location.host}/ws`;
})();

export { API_BASE, WS_BASE };

