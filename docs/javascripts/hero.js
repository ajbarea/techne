/* Hero page class must be reapplied on instant navigation transitions. */
function updateHeroPageClass() {
  const hero = document.querySelector('.hero');
  if (hero) {
    document.documentElement.classList.add('hero-page');
    document.body.classList.add('hero-page');
  } else {
    document.documentElement.classList.remove('hero-page');
    document.body.classList.remove('hero-page');
  }
}

document.addEventListener('DOMContentLoaded', updateHeroPageClass);

if (typeof document$ !== 'undefined' && typeof document$.subscribe === 'function') {
  document$.subscribe(updateHeroPageClass);
}
