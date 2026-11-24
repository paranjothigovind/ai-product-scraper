import { z } from "zod";

export const Availability = z.enum(["in_stock", "out_of_stock", "unknown"]);
export const ProductSource = z.enum(["jsonld", "microdata", "selector", "llm"]);

export const Product = z.object({
  id: z.string().min(1),
  name: z.string().min(1),
  url: z.string().url(),
  price: z.number().nonnegative().nullable(),
  currency: z.string().nullable(),
  image: z.string().url().nullable(),
  brand: z.string().nullable(),
  category: z.string().nullable(),
  rating: z.number().min(0).max(5).nullable(),
  reviewCount: z.number().int().nonnegative().nullable(),
  availability: Availability,
  description: z.string().nullable(),
  source: ProductSource,
});
export type Product = z.infer<typeof Product>;

export const RankedProduct = Product.extend({
  rank: z.number().int().positive(),
  score: z.number().min(0).max(1),
  reason: z.string().optional(),
});
export type RankedProduct = z.infer<typeof RankedProduct>;

export const Category = z.object({
  name: z.string().min(1),
  slug: z.string().min(1),
  url: z.string().url().nullable(),
  parent: z.string().nullable(),
  productCount: z.number().int().nonnegative().nullable(),
});
export type Category = z.infer<typeof Category>;
