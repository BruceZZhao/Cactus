import { BrowserRouter, Routes, Route } from 'react-router-dom';
import ChatRoom from './pages/ChatRoom';

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<ChatRoom />} />
      </Routes>
    </BrowserRouter>
  );
}

export default App;

