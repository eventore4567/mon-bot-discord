(() => {
  "use strict";

  const revealTargets = document.querySelectorAll(
    ".hero-copy > *, .hero-console, .section-heading, .feature-card, .security-stack > div, .status-panel, .cta"
  );
  revealTargets.forEach((node, index) => {
    node.classList.add("sentrix-reveal", `sentrix-reveal-delay-${Math.min(index % 4, 3)}`);
  });

  if ("IntersectionObserver" in window) {
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (!entry.isIntersecting) return;
          entry.target.classList.add("is-visible");
          observer.unobserve(entry.target);
        });
      },
      { threshold: 0.12, rootMargin: "0px 0px -7% 0px" }
    );
    revealTargets.forEach((node) => observer.observe(node));
  } else {
    revealTargets.forEach((node) => node.classList.add("is-visible"));
  }

  const statusPanel = document.querySelector(".status-panel");
  const healthButton = statusPanel?.querySelector('a[href="/healthz"]');
  const statusTitle = statusPanel?.querySelector("strong");
  const statusDetail = statusPanel?.querySelector("small");

  async function checkHealth(event) {
    event?.preventDefault();
    if (!statusPanel || !healthButton || !statusTitle || !statusDetail) return;
    const started = performance.now();
    statusPanel.dataset.health = "checking";
    healthButton.classList.add("health-live", "checking");
    healthButton.classList.remove("good", "bad");
    healthButton.textContent = "Vérification…";
    statusTitle.textContent = "Test du control plane…";
    statusDetail.textContent = "Connexion à l'API SentriX en cours";

    try {
      const response = await fetch(`/healthz?t=${Date.now()}`, {
        cache: "no-store",
        headers: { Accept: "application/json" },
      });
      const payload = await response.json();
      if (!response.ok || payload.status !== "ok") throw new Error(`HTTP ${response.status}`);
      const latency = Math.max(1, Math.round(performance.now() - started));
      statusPanel.dataset.health = "good";
      healthButton.classList.remove("checking", "bad");
      healthButton.classList.add("good");
      healthButton.textContent = `En ligne • ${latency} ms`;
      statusTitle.textContent = "Control plane opérationnel";
      statusDetail.textContent = `Health check réel réussi • latence ${latency} ms`;
    } catch {
      statusPanel.dataset.health = "bad";
      healthButton.classList.remove("checking", "good");
      healthButton.classList.add("bad");
      healthButton.textContent = "Réessayer";
      statusTitle.textContent = "Control plane indisponible";
      statusDetail.textContent = "Le health check n'a pas répondu correctement";
    }
  }

  if (healthButton) {
    healthButton.textContent = "Tester maintenant";
    healthButton.addEventListener("click", checkHealth);
    window.setTimeout(() => void checkHealth(), 900);
    window.setInterval(() => void checkHealth(), 45000);
  }
})();
