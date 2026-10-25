import { createSlideshow } from '../src/ui/slideshow.js';

describe('slideshow portrait marking', () => {
  afterEach(() => { document.body.innerHTML = ''; });

  function srcOf(el) {
    return [...el.querySelectorAll('img.ss-img')].find((im) => im.getAttribute('src'));
  }

  it.each([
    [{ width: 3000, height: 4000 }, true],
    [{ width: 4000, height: 3000 }, false],
    [{ width: 2000, height: 2000 }, false],
    [{ width: null, height: null }, false],
  ])('%o -> portrait %s', (size, portrait) => {
    const el = document.createElement('div');
    document.body.appendChild(el);
    const ss = createSlideshow(el);
    ss.setPhotos([{ id: 'a', url: 'https://x.test/a.jpg', takenAt: null, place: null, ...size }]);
    ss.start();
    expect(srcOf(el).classList.contains('is-portrait')).toBe(portrait);
    ss.stop();
  });
});
