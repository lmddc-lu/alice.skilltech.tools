import {
  MoodleCoursesData,
  MoodleCourseInfo,
  MoodleCourseStructure,
} from '../../app/interfaces/chatbot-i';

const moodleDomain = 'https://moodle.example.lu';
const now = '2026-04-01T09:00:00.000Z';

function makeCourseInfo(
  partial: Partial<MoodleCourseInfo> & { course_id: string; course_name: string }
): MoodleCourseInfo {
  return {
    shortname: null,
    description: '',
    category: 'Général',
    course_url: `${moodleDomain}/course/view.php?id=${partial.course_id}`,
    moodle_domain: moodleDomain,
    selection_key: `course:${partial.course_id}`,
    total_sections: 3,
    total_activities: 6,
    datasource_id: 'ds-moodle-main',
    datasource_name: 'Moodle principal',
    metadata_synced: true,
    last_metadata_sync: now,
    total_files: 4,
    ...partial,
  };
}

export function moodleCoursesData(chatbotId: string): MoodleCoursesData {
  return {
    chatbot_id: chatbotId,
    chatbot_name: 'Chatbot',
    knowledge_base_id: `kb-${chatbotId}`,
    linked_moodle_datasources: ['ds-moodle-main'],
    linked_courses: [
      makeCourseInfo({
        course_id: 'moodle-101',
        course_name: 'Histoire contemporaine - 1ère',
        description: 'Cours d\'histoire niveau 1ère',
        category: 'Histoire',
      }),
    ],
    available_courses: [
      makeCourseInfo({
        course_id: 'moodle-202',
        course_name: 'Économie moderne',
        description: 'Introduction à l\'économie',
        category: 'Sciences Économiques',
      }),
      makeCourseInfo({
        course_id: 'moodle-303',
        course_name: 'Mathématiques - Terminale',
        description: 'Analyse et algèbre',
        category: 'Mathématiques',
      }),
    ],
    total_linked: 1,
    total_available: 2,
    total_courses: 3,
    message: null,
  };
}

export function moodleCourseStructure(courseId: string): MoodleCourseStructure {
  return {
    course_id: courseId,
    course_name:
      courseId === 'moodle-101'
        ? 'Histoire contemporaine - 1ère'
        : courseId === 'moodle-202'
          ? 'Économie moderne'
          : 'Mathématiques - Terminale',
    sections: [
      {
        id: `${courseId}-s1`,
        name: 'Section 1 — Introduction',
        section_number: 1,
        summary: 'Vue d\'ensemble et objectifs du cours.',
        has_indexed_content: true,
        activities: [
          {
            id: `${courseId}-s1-a1`,
            name: 'Syllabus',
            type: 'resource',
            description: 'Document de présentation du cours',
            has_indexed_content: true,
            files: [
              {
                id: `${courseId}-s1-a1-f1`,
                filename: 'syllabus.pdf',
                filesize: 245_760,
                mimetype: 'application/pdf',
                selection_key: `file:${courseId}-s1-a1-f1`,
                download_url: `${moodleDomain}/mod/resource/view.php?id=${courseId}-s1-a1-f1`,
              },
            ],
            entries: [],
          },
          {
            id: `${courseId}-s1-a2`,
            name: 'Forum - présentations',
            type: 'forum',
            description: 'Présentez-vous au groupe',
            has_indexed_content: false,
            files: [],
            entries: [],
          },
          {
            id: `${courseId}-s1-a3`,
            name: 'Glossaire du cours',
            type: 'glossary',
            description: 'Termes et définitions',
            has_indexed_content: false,
            files: [],
            entries: [
              { id: `${courseId}-s1-a3-e1`, concept: 'Anachronisme' },
              { id: `${courseId}-s1-a3-e2`, concept: 'Historiographie' },
              { id: `${courseId}-s1-a3-e3`, concept: 'Source primaire' },
            ],
          },
        ],
      },
      {
        id: `${courseId}-s2`,
        name: 'Section 2 — Concepts clés',
        section_number: 2,
        summary: 'Les fondamentaux à maîtriser.',
        has_indexed_content: true,
        activities: [
          {
            id: `${courseId}-s2-a1`,
            name: 'Chapitre 1',
            type: 'resource',
            description: 'Support de cours principal',
            has_indexed_content: true,
            files: [
              {
                id: `${courseId}-s2-a1-f1`,
                filename: 'chapitre-1.pdf',
                filesize: 1_048_576,
                mimetype: 'application/pdf',
                selection_key: `file:${courseId}-s2-a1-f1`,
                download_url: `${moodleDomain}/mod/resource/view.php?id=${courseId}-s2-a1-f1`,
              },
              {
                id: `${courseId}-s2-a1-f2`,
                filename: 'chapitre-1-slides.pdf',
                filesize: 524_288,
                mimetype: 'application/pdf',
                selection_key: `file:${courseId}-s2-a1-f2`,
                download_url: `${moodleDomain}/mod/resource/view.php?id=${courseId}-s2-a1-f2`,
              },
            ],
            entries: [],
          },
          {
            id: `${courseId}-s2-a2`,
            name: 'Devoir 1',
            type: 'assignment',
            description: 'Analyse critique d\'un document',
            has_indexed_content: false,
            files: [],
            entries: [],
          },
        ],
      },
      {
        id: `${courseId}-s3`,
        name: 'Section 3 — Approfondissement',
        section_number: 3,
        summary: 'Pour aller plus loin.',
        has_indexed_content: false,
        activities: [
          {
            id: `${courseId}-s3-a1`,
            name: 'Ressources complémentaires',
            type: 'resource',
            description: 'Lectures optionnelles',
            has_indexed_content: false,
            files: [
              {
                id: `${courseId}-s3-a1-f1`,
                filename: 'bibliographie.pdf',
                filesize: 65_536,
                mimetype: 'application/pdf',
                selection_key: `file:${courseId}-s3-a1-f1`,
                download_url: `${moodleDomain}/mod/resource/view.php?id=${courseId}-s3-a1-f1`,
              },
            ],
            entries: [],
          },
        ],
      },
    ],
  };
}
