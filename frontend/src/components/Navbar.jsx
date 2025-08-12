import React, { useState } from "react";

export default function Navbar() {
  const [open, setOpen] = useState(false);

  return (
    <>
      <header className="fixed top-0 left-0 w-full z-50 bg-transparent">
        <div className="max-w-6xl mx-auto px-4 py-4 grid grid-cols-3 items-center">
          {/* Logo (left) */}
          <h1 className="text-white text-2xl font-bold">EchoMind</h1>

          {/* Nav links (centered) */}
          <nav className="hidden md:flex justify-center space-x-6 text-white">
            <a href="/" className="hover:text-gray-300">Home</a>
            <a href="/faq" className="hover:text-gray-300">FAQ</a>
          </nav>

          {/* Hamburger (right) */}
          <div className="flex justify-end md:hidden">
            <button
              className="focus:outline-none"
              onClick={() => setOpen(true)}
            >
              <svg xmlns="http://www.w3.org/2000/svg" className="w-8 h-8 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
              </svg>
            </button>
          </div>
        </div>
      </header>

      {/* Mobile overlay */}
      {open && (
        <div
          className="fixed inset-0 bg-black bg-opacity-50 z-40"
          onClick={() => setOpen(false)}
        />
      )}

      {/* Slide-out menu */}
      <div className={`fixed top-0 right-0 h-full w-2/3 max-w-xs bg-gray-900 z-50 transform transition-transform duration-300 ease-in-out
        ${open ? "translate-x-0" : "translate-x-full"}`}>
        <div className="p-6 flex flex-col space-y-4 text-white">
          <button
            className="self-end text-2xl font-bold focus:outline-none"
            onClick={() => setOpen(false)}
          >
            ✕
          </button>
          <a href="#" className="text-lg hover:text-gray-300">Home</a>
          <a href="#" className="text-lg hover:text-gray-300">About</a>
        </div>
      </div>
    </>
  );
}
