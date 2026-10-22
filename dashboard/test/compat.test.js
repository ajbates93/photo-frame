import { findViolations } from '../scripts/check-compat.mjs';

test('flags forbidden CSS', () => {
  expect(findViolations('a{color:#ffffffbf}')).toHaveLength(1);
  expect(findViolations('a{color:#0000}')).toHaveLength(1);
  expect(findViolations('a{color:color-mix(in srgb,red,blue)}')).toHaveLength(1);
  expect(findViolations('a{height:100dvh}')).toHaveLength(1);
  expect(findViolations('a{&:hover{color:red}}')).toHaveLength(1);
  expect(findViolations('a{color:#fff;background:#f2eee6;height:100vh}')).toEqual([]);
});
