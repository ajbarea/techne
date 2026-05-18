/* Hero Page Detection — Hide footer on landing page */
document.addEventListener('DOMContentLoaded', function() {
  const hero = document.querySelector('.hero');
  if (hero) {
    document.documentElement.classList.add('hero-page');
    document.body.classList.add('hero-page');
  }
});
