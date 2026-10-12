import { Circle, double as twice } from "./shapes";
import * as shapes from "./shapes";

export function run(): number {
  const c = new Circle(twice(2));
  return shapes.square(c.area());
}

run();
