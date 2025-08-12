import React from "react";
import UploadForm from "./UploadForm";

export default function Hero() {
  return (
    <section className="min-h-screen flex flex-col justify-center items-center bg-gradient-to-b from-gray-900 to-black text-white text-center px-4">
      <div className="max-w-6xl w-full px-4">
        <h1 className="text-4xl md:text-6xl font-bold mb-6">Split Your Tracks. Effortlessly.</h1>
        <p className="text-gray-300 mb-8">Upload any song and get clean stems in seconds.</p>
        <UploadForm />
      </div>
    </section>
  );
}
