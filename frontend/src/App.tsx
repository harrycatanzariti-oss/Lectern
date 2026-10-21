import { Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import Home from "./pages/Home";
import Lesson from "./pages/Lesson";
import Practice from "./pages/Practice";
import Review from "./pages/Review";
import SubjectPage from "./pages/SubjectPage";

export default function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/s/:id" element={<SubjectPage />} />
        <Route path="/s/:id/review" element={<Review />} />
        <Route path="/s/:id/practice" element={<Practice />} />
        <Route path="/t/:id" element={<Lesson />} />
        <Route path="*" element={<p className="text-neutral-500">Page not found.</p>} />
      </Routes>
    </Layout>
  );
}
