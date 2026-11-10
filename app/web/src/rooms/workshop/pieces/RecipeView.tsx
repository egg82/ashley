// A recipe piece as a card: the recipe a page published, its amounts scaled by the server for the bench's headcount
// (`piece.recipe`), a line the server could not scale marked "as written", the steps as the page wrote them, and the
// page linked. A body the server could not read is shown as the text it is.
import type { BenchPiece } from '../../../api/types';
import { recipeCard } from './recipeCard';

export function RecipeView({ piece }: { piece: BenchPiece }) {
  if (!piece.recipe) return <div class="pbody plain"><p>{piece.body}</p></div>;
  const card = recipeCard(piece.recipe);
  return (
    <div class="pbody recipe">
      <div class="recipe-head">
        <strong class="recipe-name">{card.name}</strong>
        <span class="meta">{card.makes}</span>
        {card.times && <span class="meta">{card.times}</span>}
      </div>
      <h4 class="recipe-sub">Ingredients</h4>
      <ul class="recipe-ingredients">
        {card.ingredients.map((line, i) => (
          <li key={i}>
            {line.text}
            {line.asWritten && <span class="meta recipe-as-written"> (as written)</span>}
          </li>
        ))}
      </ul>
      {card.steps.length > 0 && (
        <>
          <h4 class="recipe-sub">Steps{card.stepsNote && <span class="meta"> · {card.stepsNote}</span>}</h4>
          <ol class="recipe-steps">{card.steps.map((step, i) => <li key={i}>{step}</li>)}</ol>
        </>
      )}
      {card.source && (
        <div class="frame-foot">
          <span class="meta frame-host">{card.source.hostname}</span>
          <a class="btn sm ghost" href={card.source.href} target="_blank" rel="noopener noreferrer">Open the page</a>
        </div>
      )}
    </div>
  );
}
