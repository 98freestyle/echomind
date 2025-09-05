import React, { useContext, useState } from "react";
import { AuthContext } from "../context/AuthContext.jsx";
import { Link, useNavigate } from "react-router-dom";
import { createCheckoutSession } from "../api";

function toBool(v) {
  return v === true || v === "true" || v === 1 || v === "1";
}

export default function Navbar() {
  const { user, logout } = useContext(AuthContext);
  const [open, setOpen] = useState(false);
  const [showModal, setShowModal] = useState(false);
  const navigate = useNavigate();

  const handleLogout = () => {
    logout();
    navigate("/login");
  };

  const isPremium = toBool(user?.is_premium);
  // SHOW if logged out OR logged in & NOT premium
  const shouldShowUpgrade = !user || !isPremium;

  return (
    <>
      <header className="fixed top-0 left-0 w-full z-50 bg-gray-900/80 backdrop-blur-md border-b border-white/10">
        <div className="max-w-6xl mx-auto px-4 py-4 grid grid-cols-3 items-center">
          <Link to="/" className="text-white text-2xl font-bold">EchoMind</Link>

          <nav className="hidden md:flex justify-center space-x-6 text-white">
            <Link to="/" className="hover:text-gray-300">Home</Link>
            <Link to="/faq" className="hover:text-gray-300">FAQ</Link>
            <Link to="/contact" className="...">Contact</Link>
            {user && <Link to="/dashboard" className="hover:text-gray-300">Dashboard</Link>}
          </nav>

          <div className="hidden md:flex justify-end items-center space-x-4">
            {shouldShowUpgrade && (
              <button
                onClick={() => {
                  if (!user) {
                    navigate("/signup"); // logged out -> go sign up
                  } else {
                    setShowModal(true);  // logged in & not premium -> open modal
                  }
                }}
                className="px-3 py-2 rounded-lg bg-gradient-to-r from-indigo-500 to-fuchsia-600 text-white font-semibold shadow hover:opacity-90 transition"
              >
                Upgrade to Premium
              </button>
            )}

            {!user ? (
              <>
                <Link to="/login" className="text-white hover:text-gray-300">Login</Link>
                <Link to="/signup" className="text-white hover:text-gray-300">Sign Up</Link>
              </>
            ) : (
              <button onClick={handleLogout} className="text-white hover:text-red-400">
                Logout
              </button>
            )}
          </div>

          <div className="flex justify-end md:hidden">
            <button className="focus:outline-none" onClick={() => setOpen(true)}>
              <svg xmlns="http://www.w3.org/2000/svg" className="w-8 h-8 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
              </svg>
            </button>
          </div>
        </div>
      </header>

      {open && (
        <div className="fixed inset-0 bg-black bg-opacity-50 z-40" onClick={() => setOpen(false)} />
      )}

      <div className={`fixed top-0 right-0 h-full w-2/3 max-w-xs bg-gray-900 z-50 transform transition-transform duration-300 ease-in-out ${open ? "translate-x-0" : "translate-x-full"}`}>
        <div className="p-6 flex flex-col space-y-4 text-white">
          <button className="self-end text-2xl font-bold focus:outline-none" onClick={() => setOpen(false)}>✕</button>
          <Link to="/" className="text-lg hover:text-gray-300" onClick={() => setOpen(false)}>Home</Link>
          <Link to="/faq" className="text-lg hover:text-gray-300" onClick={() => setOpen(false)}>FAQ</Link>
          {user && (
            <Link to="/dashboard" className="text-lg hover:text-gray-300" onClick={() => setOpen(false)}>Dashboard</Link>
          )}
          {!user ? (
            <>
              <Link to="/login" className="text-lg hover:text-gray-300" onClick={() => setOpen(false)}>Login</Link>
              <Link to="/signup" className="text-lg hover:text-gray-300" onClick={() => setOpen(false)}>Sign Up</Link>
            </>
          ) : (
            <button onClick={() => { setOpen(false); handleLogout(); }} className="text-left text-lg hover:text-red-400">Logout</button>
          )}
        </div>
      </div>

      {/* Premium Modal — only for logged-in, non-premium users */}
      {showModal && user && !isPremium && (
        <div
          className="fixed inset-0 z-[60] flex items-center justify-center bg-black/60 px-4"
          onClick={() => setShowModal(false)}
        >
          <div
            className="w-full max-w-md rounded-2xl bg-gray-900 text-white p-6 shadow-2xl ring-1 ring-white/10"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-start justify-between">
              <h3 className="text-xl font-bold">Go Premium</h3>
              <button onClick={() => setShowModal(false)} className="text-gray-400 hover:text-white">✕</button>
            </div>

            <div className="mt-4 space-y-3">
              <div className="rounded-lg bg-gray-800 p-4">
                <div className="text-2xl font-extrabold">AUD $15</div>
                <div className="text-sm text-gray-300">one-time payment</div>
              </div>
              <ul className="text-sm space-y-2">
                <li className="flex items-center gap-2">
                  <span className="h-1.5 w-1.5 rounded-full bg-fuchsia-500"></span>
                  Unlock 2GB/week processing quota
                </li>
                <li className="flex items-center gap-2">
                  <span className="h-1.5 w-1.5 rounded-full bg-indigo-500"></span>
                  Priority job queue (premium goes first)
                </li>
                <li className="flex items-center gap-2">
                  <span className="h-1.5 w-1.5 rounded-full bg-emerald-500"></span>
                  Instant upgrade after payment
                </li>
              </ul>
            </div>

            <div className="mt-6 flex gap-3">
              <button
                onClick={() => {
                  if (!user?.email) {
                    navigate("/signup");
                  } else {
                    createCheckoutSession(user.email);
                  }
                }}
                className="flex-1 py-2 rounded-lg bg-gradient-to-r from-indigo-500 to-fuchsia-600 font-semibold hover:opacity-90 transition"
              >
                Upgrade now
              </button>
              <button
                onClick={() => setShowModal(false)}
                className="px-4 py-2 rounded-lg bg-gray-800 hover:bg-gray-700 transition"
              >
                Not now
              </button>
            </div>

            <p className="mt-3 text-xs text-gray-400">
              You'll be redirected to Stripe Checkout. Once you pay, your account will automatically be upgraded.
            </p>
          </div>
        </div>
      )}
    </>
  );
}
