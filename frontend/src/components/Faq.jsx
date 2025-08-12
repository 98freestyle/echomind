import React from "react";

export default function Faq() {
    const faqs = [
        {
            q: "What file types can I upload?",
            a: "You can upload MP3, WAV, FLAC, M4A, AAC, OGG, AIFF, and MP4 files.",
        },
        {
            q: "Is there a file size limit?",
            a: "Yes — files must be under 200MB by default.",
        },
        {
            q: "How long does it take to process?",
            a: "Usually under 30 seconds for typical tracks, but longer files may take more.",
        },
        {
            q: "What stems can I extract?",
            a: "Vocals, drums, bass, and other — choose any combination before uploading.",
        },
        {
            q: "Can I preview the results?",
            a: "Yes — you’ll see waveform previews with volume control for each selected stem.",
        },
        {
            q: "Do I need to create an account?",
            a: "Nope. It’s fully anonymous for now — but account features are coming soon.",
        },
    ];

    return (
        <section className="min-h-screen bg-gradient-to-b from-black to-gray-900 text-white px-6 py-24">
            <div className="max-w-4xl mx-auto">
                <h1 className="text-4xl md:text-5xl font-bold text-center mb-12">Frequently Asked Questions</h1>
                <div className="space-y-8">
                    {faqs.map((item, index) => (
                        <div key={index} className="bg-gray-800 p-6 rounded-xl shadow-md hover:shadow-lg transition duration-300">
                            <h3 className="text-xl font-semibold mb-2 text-indigo-400">{item.q}</h3>
                            <p className="text-gray-300">{item.a}</p>
                        </div>
                    ))}
                </div>
            </div>
        </section>
    );
}
