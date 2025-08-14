import React from "react";
import { Routes, Route } from "react-router-dom";
import Navbar from "./components/Navbar";
import Hero from "./components/Hero";
import Faq from "./components/Faq";
import Signup from "./components/Signup";

export default function App() {
  return (
    <div className="bg-black min-h-screen">
      <Navbar />
      <Routes>
        <Route path="/" element={<Hero />} />
        <Route path="/faq" element={<Faq />} />
        <Route path="/signup" element={<Signup />} />
      </Routes>
    </div>
  );
}
