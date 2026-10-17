import Link from 'next/link';
import {
  ArrowRight,
  BarChart3,
  Bell,
  Building2,
  Camera,
  CloudOff,
  Coffee,
  Hotel,
  Images,
  Lock,
  ScanEye,
  ShieldCheck,
  ShoppingCart,
  Store,
  UsersRound,
} from 'lucide-react';

export const metadata = {
  title: 'VIAHIND Vision — AI CCTV Business Intelligence',
  description: 'Footfall, occupancy, reviewable alerts and reports from the CCTV cameras you already have.',
};

const FEATURES = [
  {
    icon: UsersRound,
    title: 'Footfall and occupancy',
    text: 'Entries and exits counted at a line you draw on the camera image, with estimated occupancy per location and simple head-count reconciliation.',
  },
  {
    icon: BarChart3,
    title: 'Reports that answer questions',
    text: 'Peak hours, busiest weekdays, camera and branch comparisons, change against the previous period. Export CSV, print to PDF or get them by email.',
  },
  {
    icon: Bell,
    title: 'Alerts with reasons',
    text: 'Restricted areas, long waits, activity after hours, unusual traffic, cameras offline or covered, vigorous movement. Every alert says what was measured.',
  },
  {
    icon: Images,
    title: 'Evidence, not surveillance footage',
    text: 'One snapshot per recorded event, kept for the period you choose, visible only to authorised staff and deletable with an audit trail.',
  },
  {
    icon: Camera,
    title: 'Works with your cameras',
    text: 'RTSP and HTTP IP cameras, DVR/NVR outputs, USB webcams, even a phone. Built-in connection tests explain what is wrong when a stream fails.',
  },
  {
    icon: CloudOff,
    title: 'Keeps working offline',
    text: 'Video is processed on site. With cloud sync on, events wait in a local queue during an internet outage and upload later, never twice.',
  },
];

const STEPS = [
  { title: 'Connect a camera', text: 'Add the RTSP address of an existing camera or DVR channel and test the connection from the browser.' },
  { title: 'Draw a line and zones', text: 'Mark the doorway to count, and any area you want watched, directly on the live image.' },
  { title: 'Read the figures', text: 'Occupancy, footfall and alerts update in real time; reports and scheduled summaries follow.' },
];

const INDUSTRIES = [
  { icon: ShoppingCart, title: 'Retail and supermarkets', text: 'Footfall by hour, staffing for peaks, after-hours activity.' },
  { icon: Coffee, title: 'Restaurants and cafés', text: 'Busy periods, occupancy against seating capacity.' },
  { icon: Hotel, title: 'Hotels and hospitality', text: 'Lobby traffic, restricted service areas, long waits at reception.' },
  { icon: Building2, title: 'Offices and properties', text: 'Out-of-hours entries, multi-site comparisons, camera health.' },
];

const PRINCIPLES = [
  'People are counted, not identified. Labels like “Unknown Person 07” are temporary tracking labels that reset when a camera reconnects.',
  'No face recognition. The product is designed to be useful without biometrics.',
  'Alerts are prompts for a person to review, never proof of wrongdoing.',
  'Only event snapshots are stored, never continuous video, with retention you control.',
  'Each business sees only its own data; every administrative action is audited.',
  'Camera passwords are encrypted and never shown, logged or sent to the cloud.',
];

const FAQ = [
  ['Do I need new cameras?', 'Usually not. Any camera or DVR/NVR that provides an RTSP or HTTP stream works, and a USB webcam or phone is enough to try it.'],
  ['How accurate is the count?', 'It depends on the camera position. Crowds crossing together, occlusion and doors without a counting camera cause drift, which is why occupancy is shown as an estimate with a one-click reconciliation.'],
  ['Can it detect fights?', 'Without a trained model it reports vigorous movement between people in close contact, labelled honestly as such. A trainable altercation classifier is included; either way, every detection is reviewed by a person.'],
  ['Where is my video processed?', 'On a computer at your premises. Only event figures are synchronised if you enable the cloud dashboard; images and camera credentials stay on site.'],
];

export default function Home() {
  return (
    <div className="site">
      <header className="site-header">
        <div className="site-wrap site-header-row">
          <Link href="/" className="site-brand" aria-label="VIAHIND Vision home">
            <span className="brand-mark" aria-hidden="true">
              <ScanEye size={18} />
            </span>
            <span>VIAHIND Vision</span>
          </Link>
          <nav className="site-nav" aria-label="Website">
            <a href="#features">Features</a>
            <a href="#how">How it works</a>
            <a href="#privacy">Privacy</a>
            <a href="#faq">FAQ</a>
          </nav>
          <div className="site-actions">
            <Link href="/login" className="btn btn-ghost">
              Sign in
            </Link>
            <Link href="/overview" className="btn btn-primary">
              Open console
            </Link>
          </div>
        </div>
      </header>

      <main>
        <section className="site-hero">
          <div className="site-wrap site-hero-grid">
            <div>
              <p className="site-eyebrow">AI CCTV business intelligence</p>
              <h1>Understand what happens at your premises, from the cameras you already have.</h1>
              <p className="site-lead">
                VIAHIND Vision turns CCTV into footfall, occupancy, reviewable alerts and clear reports for shops, restaurants, hotels and
                offices — processed on site, with privacy built in.
              </p>
              <div className="site-cta">
                <Link href="/login" className="btn btn-primary btn-lg">
                  Sign in to your console <ArrowRight size={16} />
                </Link>
                <a href="#how" className="btn btn-lg">
                  See how it works
                </a>
              </div>
            </div>
            <div className="site-hero-card" aria-hidden="true">
              <div className="site-hero-card-head">
                <span className="dot" style={{ color: 'var(--ok)' }} /> What your dashboard shows
              </div>
              <ul>
                <li>
                  <UsersRound size={16} /> Estimated occupancy, per location
                </li>
                <li>
                  <BarChart3 size={16} /> Entries and exits by hour, today vs yesterday
                </li>
                <li>
                  <Bell size={16} /> Open alerts with their reasons
                </li>
                <li>
                  <Camera size={16} /> Which cameras are live, and since when
                </li>
                <li>
                  <Store size={16} /> All your branches side by side
                </li>
              </ul>
            </div>
          </div>
        </section>

        <section id="features" className="site-section">
          <div className="site-wrap">
            <h2>Everything a business owner needs from CCTV</h2>
            <p className="site-sub">Figures you can act on, alerts you can trust to explain themselves, and nothing you do not need.</p>
            <div className="site-grid">
              {FEATURES.map(({ icon: Icon, title, text }) => (
                <article key={title} className="site-card">
                  <Icon size={20} aria-hidden="true" className="site-card-icon" />
                  <h3>{title}</h3>
                  <p>{text}</p>
                </article>
              ))}
            </div>
          </div>
        </section>

        <section id="how" className="site-section site-section-alt">
          <div className="site-wrap">
            <h2>Up and running in an afternoon</h2>
            <ol className="site-steps">
              {STEPS.map((s, i) => (
                <li key={s.title}>
                  <span className="site-step-no">{i + 1}</span>
                  <h3>{s.title}</h3>
                  <p>{s.text}</p>
                </li>
              ))}
            </ol>
            <div className="site-grid site-grid-4" style={{ marginTop: 32 }}>
              {INDUSTRIES.map(({ icon: Icon, title, text }) => (
                <article key={title} className="site-card">
                  <Icon size={20} aria-hidden="true" className="site-card-icon" />
                  <h3>{title}</h3>
                  <p>{text}</p>
                </article>
              ))}
            </div>
          </div>
        </section>

        <section id="privacy" className="site-section">
          <div className="site-wrap site-two-col">
            <div>
              <ShieldCheck size={28} aria-hidden="true" className="site-card-icon" />
              <h2>Responsible by design</h2>
              <p className="site-sub">
                Cameras see customers and staff. VIAHIND Vision is built so you learn about your business without building a profile of
                anyone in it.
              </p>
              <p className="small muted">
                You remain responsible for using it lawfully: display signage, limit access and keep retention short (in India, see the
                Digital Personal Data Protection Act, 2023).
              </p>
            </div>
            <ul className="site-checklist">
              {PRINCIPLES.map((p) => (
                <li key={p}>
                  <Lock size={15} aria-hidden="true" />
                  <span>{p}</span>
                </li>
              ))}
            </ul>
          </div>
        </section>

        <section id="faq" className="site-section site-section-alt">
          <div className="site-wrap">
            <h2>Questions</h2>
            <div className="site-faq">
              {FAQ.map(([q, a]) => (
                <details key={q}>
                  <summary>{q}</summary>
                  <p>{a}</p>
                </details>
              ))}
            </div>
          </div>
        </section>

        <section className="site-section site-final">
          <div className="site-wrap" style={{ textAlign: 'center' }}>
            <h2>Ready to see your premises in numbers?</h2>
            <p className="site-sub">Sign in to configure your first camera, or ask your administrator for an account.</p>
            <Link href="/login" className="btn btn-primary btn-lg">
              Sign in <ArrowRight size={16} />
            </Link>
          </div>
        </section>
      </main>

      <footer className="site-footer">
        <div className="site-wrap site-header-row">
          <span>© VIAHIND Vision · AI CCTV business intelligence</span>
          <nav className="site-nav" aria-label="Footer">
            <a href="#privacy">Privacy principles</a>
            <a href="#faq">FAQ</a>
            <Link href="/login">Sign in</Link>
          </nav>
        </div>
      </footer>
    </div>
  );
}
