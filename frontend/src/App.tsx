import { useEffect, useState } from "react";
import { Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import { ErrorNote, Spinner, btnPrimary, card } from "./components/ui";
import { api, setSignedOutHandler } from "./lib/api";
import Exam from "./pages/Exam";
import Home from "./pages/Home";
import Lesson from "./pages/Lesson";
import Practice from "./pages/Practice";
import Review from "./pages/Review";
import SubjectPage from "./pages/SubjectPage";

function SignIn({ onSignedIn }: { onSignedIn: () => void }) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  return (
    <form
      className={`${card} mx-auto mt-16 max-w-sm space-y-4 p-6`}
      onSubmit={async (e) => {
        e.preventDefault();
        try {
          await api.login(password);
          onSignedIn();
        } catch (err) {
          setError((err as Error).message);
        }
      }}
    >
      <h1 className="text-lg font-semibold">Sign in</h1>
      <input
        type="password"
        autoFocus
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        placeholder="Password"
        className="w-full rounded-lg border border-neutral-300 bg-white px-3 py-2 outline-none focus:border-brand"
      />
      {error && <ErrorNote error={error} />}
      <button className={btnPrimary}>Sign in</button>
    </form>
  );
}

export default function App() {
  const [signedIn, setSignedIn] = useState<boolean | null>(null);

  useEffect(() => {
    setSignedOutHandler(() => setSignedIn(false));
    api.session().then((s) => setSignedIn(s.signed_in), () => setSignedIn(true));
  }, []);

  return (
    <Layout>
      {signedIn === null ? (
        <Spinner />
      ) : !signedIn ? (
        <SignIn onSignedIn={() => setSignedIn(true)} />
      ) : (
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/review" element={<Review />} />
          <Route path="/s/:id" element={<SubjectPage />} />
          <Route path="/s/:id/review" element={<Review />} />
          <Route path="/s/:id/practice" element={<Practice />} />
          <Route path="/s/:id/exam" element={<Exam />} />
          <Route path="/t/:id" element={<Lesson />} />
          <Route path="*" element={<p className="text-neutral-500">Page not found.</p>} />
        </Routes>
      )}
    </Layout>
  );
}
