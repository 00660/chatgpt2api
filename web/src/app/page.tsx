export default function HomePage() {
  return (
    <div className="grid min-h-[calc(100vh-1rem)] w-full place-items-center px-4 py-6">
      <meta httpEquiv="refresh" content="0;url=/login/" />
      <a
        href="/login/"
        className="rounded-2xl bg-stone-950 px-5 py-3 text-sm font-medium text-white shadow-sm"
      >
        进入登录页
      </a>
    </div>
  );
}
