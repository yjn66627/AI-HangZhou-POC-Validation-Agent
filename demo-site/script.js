(() => {
  const video = document.querySelector(".video-frame video");
  const placeholder = document.querySelector(".video-placeholder");

  if (video && placeholder) {
    video.addEventListener("error", () => {
      placeholder.style.display = "flex";
      video.style.display = "none";
    });
    video.addEventListener("loadeddata", () => {
      placeholder.style.display = "none";
      video.style.display = "block";
    });
  }

  document.querySelectorAll('a[href^="#"]').forEach((link) => {
    link.addEventListener("click", (event) => {
      const target = document.querySelector(link.getAttribute("href"));
      if (!target) return;
      event.preventDefault();
      target.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  });
})();
