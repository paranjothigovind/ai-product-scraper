"use client";

import { useState } from "react";

/** A product thumbnail that falls back to an empty box if the image will not load. */
export function ProductImage({ src }: { src: string | undefined }) {
  const [failed, setFailed] = useState(false);
  return (
    <div className="h-20 w-20 shrink-0 overflow-hidden rounded-lg bg-neutral-100 dark:bg-neutral-800">
      {src && !failed && (
        // Product images come from arbitrary sites, so next/image's allow-list cannot apply.
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={src}
          alt=""
          loading="lazy"
          referrerPolicy="no-referrer"
          onError={() => setFailed(true)}
          className="h-full w-full object-cover"
        />
      )}
    </div>
  );
}
