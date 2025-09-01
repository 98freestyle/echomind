import React from "react";

export default function Faq() {
    const faqs = [
        {
            q: "What is EchoMind?",
            a: "EchoMind lets you split any song into clean, studio-quality stems, directly in your browser. No login required.",
        },
        {
            q: "Do I need an account?",
            a: "Nope! You can upload anonymously as a guest. Creating an account unlocks more weekly usage, and premium users unlock even higher limits plus priority speed.",
        },
        {
            q: "What file types are supported?",
            a: "You can upload MP3, WAV, FLAC, M4A, AAC, OGG, AIFF, or MP4 files. We extract the audio and process it automatically.",
        },
        {
            q: "What stems can I choose?",
            a: "You can pick any combo of vocals, drums, bass, and other. We use advanced fallback logic to ensure 'other' always works, even if the model fails.",
        },
        {
            q: "Is there a file size or length limit?",
            a: "Yes. Tracks must be under 200MB and less than 10 minutes long. Larger files will be rejected during upload.",
        },
        {
            q: "Can I preview stems before downloading?",
            a: "Yes! Once your job finishes, you’ll get volume-adjustable waveform previews for each selected stem.",
        },
        {
            q: "How long does it take to process a file?",
            a: "Depends on the file length. A 5 minute file may take up to 2 minutes max, but files under 2 minutes typically take 30–60 seconds. Premium users are prioritized in the queue and are always processed first.",
        },
        {
            q: "What are the weekly usage caps?",
            a: "Guests get 150MB/week, verified users get 500MB/week, and Premium accounts get 3GB/week. Usage resets every Monday at 12:00 AM AEST.",
        },
        {
            q: "Do you store my audio?",
            a: "No. All uploads and processed stems auto-delete after 5 minutes or once downloaded. We do not save any audio or personal data.",
        },
        {
            q: "Can I use this for commercial projects?",
            a: "Yes, but make sure you have legal rights to use any audio you upload. EchoMind is a technical tool, not a license provider.",
        },
    ];

    return (
        <section className="min-h-screen bg-gradient-to-b from-gray-900 to-black text-white px-6 py-24">
            <div className="max-w-4xl mx-auto">
                <h1 className="text-4xl md:text-5xl font-bold text-center mb-12">
                    Frequently Asked Questions
                </h1>
                <div className="space-y-8">
                    {faqs.map((item, index) => (
                        <div
                            key={index}
                            className="bg-gray-800/80 p-6 rounded-xl shadow-lg hover:shadow-xl transition duration-300 border border-gray-700 hover:border-indigo-500"
                        >
                            <h3 className="text-xl font-semibold mb-2 text-indigo-400">
                                {item.q}
                            </h3>
                            <p className="text-gray-300">{item.a}</p>
                        </div>
                    ))}
                </div>
            </div>
        </section>
    );
}
