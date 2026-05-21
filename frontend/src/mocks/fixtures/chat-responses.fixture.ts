export interface ChatCitationFixture {
  id: number;
  file_name: string;
  file_id: string | null;
  source_url?: string | null;
  score: number | null;
}

export interface ChatReplyFixture {
  tokens: string[];
  citations?: ChatCitationFixture[];
}

function tokenize(text: string): string[] {
  return text.match(/\S+\s*|\s+/g) ?? [text];
}

const longText = Array.from({ length: 400 }, (_, i) =>
  `Ceci est le paragraphe ${i + 1} d'une très longue réponse conçue pour tester le défilement et la mise en page. `
).join('');

export const chatResponses: Record<string, ChatReplyFixture> = {
  '*': {
    tokens: tokenize(
      'Bonjour ! Je suis votre assistant. Posez-moi une question sur le contenu indexé et je ferai de mon mieux pour y répondre.'
    ),
  },
  napoléon: {
    tokens: tokenize(
      'Napoléon Bonaparte (1769-1821) fut un général et empereur français. Il a profondément transformé la France par le Code civil, l\'administration centralisée et ses campagnes militaires à travers l\'Europe.'
    ),
  },
  révolution: {
    tokens: tokenize(
      'La Révolution française (1789-1799) a mis fin à la monarchie absolue et instauré les principes de liberté, égalité et fraternité. Elle débute avec la prise de la Bastille le 14 juillet 1789.'
    ),
  },
  inflation: {
    tokens: tokenize(
      'L\'inflation est la hausse généralisée et durable des prix des biens et services dans une économie. Elle réduit le pouvoir d\'achat de la monnaie.'
    ),
  },
  mathématiques: {
    tokens: tokenize(
      'Les mathématiques en Terminale couvrent l\'analyse (limites, dérivées, intégrales), l\'algèbre linéaire et les probabilités.'
    ),
  },
  __long__: {
    tokens: tokenize(longText),
  },
  __citations__: {
    tokens: tokenize(
      'Selon le chapitre 1 [1], la Révolution française démarre en 1789. Les notes de cours [2] précisent le rôle des États généraux.'
    ),
    citations: [
      {
        id: 1,
        file_name: 'chapitre-1-revolution-francaise.pdf',
        file_id: 'file-ready-pdf',
        source_url: null,
        score: 0.92,
      },
      {
        id: 2,
        file_name: 'notes-de-cours.docx',
        file_id: 'file-ready-docx',
        source_url: null,
        score: 0.84,
      },
    ],
  },
};

export function pickReplyFromFixture(
  userMessage: string,
  citeSources = false
): ChatReplyFixture {
  const lower = userMessage.toLowerCase();
  if (lower.includes('__long__')) return chatResponses['__long__']!;
  if (lower.includes('source') || lower.includes('citation')) {
    return chatResponses['__citations__']!;
  }
  let reply: ChatReplyFixture = chatResponses['*']!;
  for (const key of Object.keys(chatResponses)) {
    if (key === '*' || key.startsWith('__')) continue;
    if (lower.includes(key)) {
      reply = chatResponses[key]!;
      break;
    }
  }
  if (citeSources && !reply.citations) {
    const citations = chatResponses['__citations__']!.citations!;
    const markers = citations.map((c) => `[${c.id}]`).join('');
    return {
      tokens: [...reply.tokens, ` ${markers}`],
      citations,
    };
  }
  return reply;
}
